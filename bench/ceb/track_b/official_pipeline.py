"""Track B official source-build pipeline (P1.2).

Source-first evaluation:
  1. resolve the baseline tree (third_party/stockfish at the pinned ref, or
     an explicit --baseline-src for toy/test trees)
  2. scan the candidate tree (diff whitelist + content rules)
  3. build baseline and candidate with the SAME build script
  4. play candidate-vs-baseline paired matches (internal runner; the
     candidate may be jailed)
  5. write a delta-Elo report with CI and reproducibility metadata

Build convention: each tree provides an executable build script
(default ceb_build.sh) that produces an engine at a relative path
(default ceb_engine). For real Stockfish, operators supply
--build-script/--engine-relpath wrappers around `make -C src build`;
CI and tests use tiny fake trees. Binary-only self-reporting stays
diagnostic; this pipeline is the path to verified Track B results.
"""

import json
import subprocess
import time
from pathlib import Path

from ceb import paths
from ceb.hosted.metadata import build_metadata, hash_directory
from ceb.hosted.models import SCHEMA_TRACK_B_RESULT
from ceb.hosted.signing import sign_official_result
from ceb.sanitize import SanitizedError
from ceb.scan.track_b_scan import scan_track_b
from ceb.scan.leak_scan import scan_public_artifacts
from ceb.storage import VISIBILITY_PRIVATE, VISIBILITY_PUBLIC, write_artifact
from ceb.track_b.round_runner import run_track_b_round, TrackBRoundError
from ceb.track_b.stockfish import load_lock

DEFAULT_BUILD_SCRIPT = "ceb_build.sh"
DEFAULT_ENGINE_RELPATH = "ceb_engine"


class TrackBPipelineError(SanitizedError, RuntimeError):
    pass


def _build_tree(tree, build_script, engine_relpath, timeout_s=1800):
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


def run_official_track_b(*, candidate_src, baseline_src=None,
                         eval_pack_dir=None, engine_jail="none",
                         build_script=DEFAULT_BUILD_SCRIPT,
                         engine_relpath=DEFAULT_ENGINE_RELPATH,
                         games=8, movetime_ms=100, max_plies=300,
                         run_id="track_b_official", round_number=1,
                         runs_root=None, root=None, verified=False,
                         profile=None, verification_grade=None,
                         progress=lambda msg: None):
    """Run the source-first Track B pipeline. Returns the report dict.

    verified=True is reserved for the hosted worker; direct CLI use writes
    verified=False (diagnostic). When an eval pack is supplied, public
    artifacts are leak-scanned (P0.8) before the result is returned.
    """
    if root is None:
        root = paths.find_repo_root()
    runs_root = Path(runs_root) if runs_root else paths.runs_dir(root)
    candidate_src = Path(candidate_src).resolve()

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

    progress("building baseline ...")
    baseline_engine = _build_tree(baseline_src, build_script, engine_relpath)
    progress("building candidate (same script) ...")
    candidate_engine = _build_tree(candidate_src, build_script, engine_relpath)

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
        random_seed=1000 * round_number, verified=verified,
    )
    metadata["track_b"] = {
        "baseline_tree_hash": hash_directory(baseline_src),
        "candidate_tree_hash": hash_directory(candidate_src),
        "build_script": build_script,
    }

    report = {
        "schema": SCHEMA_TRACK_B_RESULT,
        "run_id": run_id,
        "track": "B",
        "round": round_number,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "engine_jail": engine_jail,
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
    sign_official_result(report)
    out_dir = runs_root / run_id / ("track_b_official_%d" % round_number)
    write_artifact(out_dir, "official_result.json", report, VISIBILITY_PUBLIC)
    write_artifact(out_dir, "scan_report.json", scan_report, VISIBILITY_PRIVATE)

    # Public-artifact leak scan (P0.8) when a private opening pack was used.
    if eval_pack_dir:
        leak_report = scan_public_artifacts(out_dir, eval_pack_dir, root)
        write_artifact(out_dir, "leak_scan.json", leak_report, VISIBILITY_PRIVATE)
        if not leak_report["passed"]:
            raise TrackBPipelineError(
                "public artifact leak scan failed: a hidden opening-pack secret "
                "would have been exposed; verification refused",
                "track B leak scan failed: %s" % json.dumps(leak_report))
    return report
