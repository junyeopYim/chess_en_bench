"""Track B source-first pipeline (diagnostic + hosted-verified).

Source-first evaluation:
  1. resolve the baseline tree (third_party/stockfish at the pinned ref, or an
     explicit --baseline-src for toy/test trees)
  2. scan the candidate tree (diff whitelist + content rules)
  3. build baseline and candidate with the SAME build strategy:
       - "host":  run each tree's own build script on the host (DIAGNOSTIC ONLY;
                  never produces a verified result)
       - "jail":  build inside the Docker build jail using a TRUSTED operator
                  wrapper outside the candidate tree (the verified path, C)
  4. play candidate-vs-baseline matches (internal runner; the candidate engine
     runs in the engine jail for verified)
  5. write a STAGED public result, leak-scan it, then promote (D), with
     reproducibility metadata and an Ed25519 signature (B)

Verified Track B (verified=True) REFUSES the host build path; the hosted worker
supplies build_isolation="jail" and a trusted wrapper. The diagnostic CLI path
keeps the host build and is always verified=False.
"""

import json
import subprocess
import time
from pathlib import Path

from ceb import paths
from ceb.hosted.metadata import build_metadata, hash_directory
from ceb.hosted.models import SCHEMA_TRACK_B_RESULT
from ceb.hosted.signing import ALGORITHM_ED25519, sign_official_result
from ceb.sanitize import SanitizedError
from ceb.scan.track_b_scan import scan_track_b
from ceb.scan.leak_scan import scan_public_artifacts
from ceb.storage import VISIBILITY_PRIVATE, write_artifact
from ceb.storage.promotion import (
    promote_public_artifacts, write_staged_public_artifact)
from ceb.track_b.round_runner import run_track_b_round, TrackBRoundError
from ceb.track_b.stockfish import load_lock

DEFAULT_BUILD_SCRIPT = "ceb_build.sh"
DEFAULT_ENGINE_RELPATH = "ceb_engine"


class TrackBPipelineError(SanitizedError, RuntimeError):
    pass


def _build_tree_host(tree, build_script, engine_relpath, timeout_s=1800):
    """DIAGNOSTIC host build: run the tree's own build script. Never verified."""
    tree = Path(tree).resolve()
    script = tree / build_script
    if not script.is_file():
        raise TrackBPipelineError(
            "build script %r not found in %s" % (build_script, tree.name),
            "build script %s not found" % script)
    proc = subprocess.run(["bash", str(script)], cwd=str(tree),
                          capture_output=True, text=True, timeout=timeout_s)
    if proc.returncode != 0:
        raise TrackBPipelineError(
            "build failed for %s (exit %d)" % (tree.name, proc.returncode),
            "build failed for %s: %s" % (tree, (proc.stderr or "")[-500:]))
    engine = tree / engine_relpath
    if not engine.is_file():
        raise TrackBPipelineError(
            "build did not produce %r in %s" % (engine_relpath, tree.name))
    engine.chmod(engine.stat().st_mode | 0o111)
    return engine


def _run_bench(baseline_engine, candidate_engine, engine_jail, min_nps_ratio):
    """Bench both engines; the candidate is jailed when jailing is on."""
    from ceb.track_b.bench_sanity import run_bench_sanity, DEFAULT_MIN_NPS_RATIO
    base_cmd = [str(baseline_engine)]
    cand_engine = Path(candidate_engine)
    cand_cmd = [str(cand_engine)]
    if engine_jail == "docker":
        from ceb.jail import engine_command, EngineJailError
        try:
            cand_cmd, _ = engine_command(cand_engine.parent, "docker",
                                         engine_name=cand_engine.name)
        except EngineJailError:
            cand_cmd = [str(cand_engine)]
    try:
        return run_bench_sanity(
            base_cmd, cand_cmd,
            min_nps_ratio=(min_nps_ratio if min_nps_ratio is not None
                           else DEFAULT_MIN_NPS_RATIO))
    finally:
        if engine_jail == "docker":
            from ceb.jail import cleanup_jails
            cleanup_jails()


def _build_jail_image_digest():
    from ceb.hosted.metadata import image_digest
    from ceb.track_b.build_jail import BUILD_JAIL_IMAGE
    return image_digest(BUILD_JAIL_IMAGE)


def run_official_track_b(*, candidate_src, baseline_src=None,
                         eval_pack_dir=None, engine_jail="none",
                         build_script=DEFAULT_BUILD_SCRIPT,
                         engine_relpath=DEFAULT_ENGINE_RELPATH,
                         games=8, movetime_ms=100, max_plies=300,
                         run_id="track_b_official", round_number=1,
                         runs_root=None, root=None, verified=False,
                         profile=None, verification_grade=None,
                         build_isolation="host", build_wrapper=None,
                         signing_key_path=None, trust=None, baseline_trust=None,
                         build_wrapper_hash=None, bench_min_nps_ratio=None,
                         allow_no_bench=False, progress=lambda msg: None):
    """Run the source-first Track B pipeline. Returns the report dict."""
    if root is None:
        root = paths.find_repo_root()
    runs_root = Path(runs_root) if runs_root else paths.runs_dir(root)
    candidate_src = Path(candidate_src).resolve()

    if verified and build_isolation != "jail":
        raise TrackBPipelineError(
            "verified Track B must build in the isolated build jail; the host "
            "build path is diagnostic only and cannot produce a verified result")
    # A verified result requires a pack so the public artifact is leak-scanned
    # before promotion (defense in depth — the hosted entry enforces this too).
    if verified and not eval_pack_dir:
        raise TrackBPipelineError(
            "verified Track B requires an eval pack so the public result is "
            "leak-scanned before promotion")

    if baseline_src is None:
        baseline_src = root / "third_party" / "stockfish"
        if not baseline_src.is_dir():
            raise TrackBPipelineError(
                "no baseline source: third_party/stockfish is absent and no "
                "--baseline-src was given. Run scripts/setup_stockfish.sh "
                "(pinned %s) or pass a baseline tree."
                % load_lock(root).get("tag", "sf_18"))
    baseline_src = Path(baseline_src).resolve()

    progress("scanning candidate tree against baseline ...")
    scan_report = scan_track_b(baseline_src, candidate_src, root=root)
    if not scan_report["passed"]:
        raise TrackBPipelineError(
            "candidate rejected by the Track B scanner (%d finding(s), "
            "%d whitelist violation(s))"
            % (len(scan_report["findings"]),
               len(scan_report["diff_check"]["violations"])),
            json.dumps(scan_report, indent=2))

    if build_isolation == "jail":
        from ceb.track_b.build_jail import build_in_jail, BuildJailError
        from ceb.hosted.build_wrappers import (
            validate_build_wrapper, BuildWrapperError)
        if not build_wrapper:
            raise TrackBPipelineError(
                "isolated Track B build requires a trusted build wrapper")
        # Defense in depth: re-validate the wrapper lives OUTSIDE the candidate/
        # baseline trees here too, not only at the hosted entry point.
        try:
            build_wrapper = str(validate_build_wrapper(
                build_wrapper, candidate_src=candidate_src,
                baseline_src=baseline_src))
        except BuildWrapperError as exc:
            raise TrackBPipelineError(
                "trusted build wrapper rejected: %s" % exc.public_message)
        build_root = runs_root / run_id / ("tb_build_%d" % round_number)
        try:
            progress("building baseline in build jail (trusted wrapper) ...")
            baseline_engine = build_in_jail(
                baseline_src, build_wrapper, engine_relpath,
                output_dir=build_root / "baseline")
            progress("building candidate in build jail (same wrapper) ...")
            candidate_engine = build_in_jail(
                candidate_src, build_wrapper, engine_relpath,
                output_dir=build_root / "candidate")
        except BuildJailError as exc:
            raise TrackBPipelineError("isolated build failed: %s" % exc)
        build_output = {
            "baseline_output_hash": hash_directory(build_root / "baseline"),
            "candidate_output_hash": hash_directory(build_root / "candidate"),
        }
    else:
        progress("building baseline (host; diagnostic) ...")
        baseline_engine = _build_tree_host(baseline_src, build_script, engine_relpath)
        progress("building candidate (host; same script; diagnostic) ...")
        candidate_engine = _build_tree_host(candidate_src, build_script, engine_relpath)
        build_output = None

    # Bench / speed sanity (req 6): record node counts / NPS; enforce the
    # NPS-ratio threshold only when both engines actually support `bench`
    # (toy engines do not). The candidate is jailed for bench when jailing.
    progress("bench/speed sanity ...")
    bench_report = _run_bench(baseline_engine, candidate_engine, engine_jail,
                              bench_min_nps_ratio)
    if verified and bench_report["supported"] and not bench_report["passed"]:
        if not allow_no_bench:
            raise TrackBPipelineError(
                "verified Track B failed bench/speed sanity: candidate NPS "
                "ratio %.3f is below the threshold %.3f"
                % (bench_report.get("nps_ratio") or 0.0,
                   bench_report["min_nps_ratio"]))

    progress("running candidate-vs-baseline match ...")
    match_report, feedback = run_track_b_round(
        [str(candidate_engine)], [str(baseline_engine)],
        round_number=round_number, run_id=run_id, games=games,
        movetime_ms=movetime_ms, max_plies=max_plies,
        eval_pack_dir=eval_pack_dir, engine_jail=engine_jail,
        runs_root=runs_root, root=root, progress=progress)

    metadata = build_metadata(
        root=root, eval_pack_dir=eval_pack_dir,
        eval_pack_id=match_report["eval_pack"]["name"]
        if isinstance(match_report.get("eval_pack"), dict) else None,
        opening_suite=match_report.get("openings_used"),
        random_seed=1000 * round_number, verified=verified)
    metadata["track_b"] = {
        "baseline_tree_hash": hash_directory(baseline_src),
        "candidate_tree_hash": hash_directory(candidate_src),
        "build_isolation": build_isolation,
        "build_script": build_script if build_isolation == "host" else None,
        "build_wrapper": str(build_wrapper) if build_wrapper else None,
        "build_wrapper_hash": build_wrapper_hash,
        "build_wrapper_trusted": bool(verified and build_wrapper_hash),
        "build_output": build_output,
        "build_jail_image_digest": (
            _build_jail_image_digest() if build_isolation == "jail" else None),
        "bench": bench_report,
        # Baseline trust (req 3).
        "baseline_trusted": bool(baseline_trust
                                 and baseline_trust.get("baseline_trusted")),
        "baseline_trust_mode": (baseline_trust.get("baseline_trust_mode")
                                if baseline_trust else None),
        "stockfish_lock": (baseline_trust.get("stockfish_lock")
                           if baseline_trust else None),
    }
    metadata["eval_pack_trusted"] = bool(verified and trust)
    if trust:
        metadata["eval_pack_id"] = trust["pack_id"]
        metadata["eval_pack_manifest_hash"] = trust["manifest_hash"]
        metadata["eval_pack_track"] = trust["track"]
        metadata["eval_pack_season"] = trust["season"]

    report = {
        "schema": SCHEMA_TRACK_B_RESULT,
        "run_id": run_id,
        "track": "B",
        "round": round_number,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "engine_jail": engine_jail,
        "build_isolation": build_isolation,
        "scan": {"passed": True},
        "score": match_report["score"],
        "feedback": feedback,
        "metadata": metadata,
        "verified": bool(verified),
    }
    if profile is not None:
        report["profile"] = profile
    if verification_grade is not None:
        report["verification_grade"] = verification_grade

    sign_official_result(report, private_key_path=signing_key_path)
    if verified and report["signature"].get("algorithm") != ALGORITHM_ED25519:
        raise TrackBPipelineError(
            "internal error: verified Track B result is not Ed25519-signed")

    out_dir = runs_root / run_id / ("track_b_official_%d" % round_number)
    write_staged_public_artifact(out_dir, "official_result.json", report)
    write_artifact(out_dir, "scan_report.json", scan_report, VISIBILITY_PRIVATE)

    if eval_pack_dir:
        leak_report = scan_public_artifacts(out_dir, eval_pack_dir, root,
                                            staged=True)
        write_artifact(out_dir, "leak_scan.json", leak_report, VISIBILITY_PRIVATE)
        if not leak_report["passed"]:
            raise TrackBPipelineError(
                "public artifact leak scan failed: a hidden opening-pack secret "
                "would have been exposed; verification refused",
                "track B leak scan failed: %s" % json.dumps(leak_report))
    promote_public_artifacts(out_dir)
    return report
