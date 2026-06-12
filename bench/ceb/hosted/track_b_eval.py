"""Hosted Track B official evaluation (v0.3.3 trust anchors).

A verified Track B result requires, beyond v0.3.2's guarantees:

  - a PINNED trusted official opening pack (req 1),
  - a TRUSTED baseline: a pinned Stockfish checkout matching stockfish.lock, or
    a hash-allowlisted baseline tree (req 3),
  - a HASH-PINNED trusted build wrapper outside the candidate tree (req 4),
  - validated build output (req 5, in build_jail) and bench/speed sanity (req 6,
    in official_pipeline), plus the v0.3.2 engine jail, Ed25519 signature, and
    staged->scan->promote.

Each untrusted anchor either hard-fails (no result) or, with its DEV flag,
downgrades the result to a diagnostic (verified=false, never on the
leaderboard). The first untrusted anchor decides the grade.
"""

from pathlib import Path

from ceb import paths
from ceb.hosted.eval_pack_trust import (
    resolve_allowed_hashes, validate_official_eval_pack, EvalPackTrustError)
from ceb.hosted.profiles import (
    PROFILE_OFFICIAL, GRADE_DIAGNOSTIC_UNJAILED, GRADE_DIAGNOSTIC_UNSIGNED,
    GRADE_DIAGNOSTIC_UNTRUSTED_PACK, GRADE_DIAGNOSTIC_UNPINNED_PACK,
    GRADE_DIAGNOSTIC_UNTRUSTED_BASELINE, GRADE_DIAGNOSTIC_UNTRUSTED_WRAPPER,
    TRACK_B_OFFICIAL_MODE, get_profile)
from ceb.hosted.signing import ed25519_private_key_path
from ceb.sanitize import private_detail
from ceb.track_b.baseline_trust import (
    resolve_baseline_hashes, validate_track_b_baseline, BaselineTrustError)
from ceb.track_b.official_pipeline import (
    run_official_track_b, TrackBPipelineError)

_MATCH_SIZE = {
    "diagnostic": (2, 30, 40),
    "official": (200, 200, 300),
    "final": (1000, 1000, 300),
}


def run_hosted_track_b(*, run_id, candidate_src, baseline_src, build_script,
                       engine_relpath, eval_pack_dir, out_dir, engine_jail,
                       profile=None, allow_unjailed=False, quick_test_mode=False,
                       official_pack_hashes=None, official_pack_registry=None,
                       allow_demo_pack=False, allow_unpinned_pack=False,
                       signing_key_path=None, allow_unsigned=False,
                       build_wrapper=None, build_wrapper_hashes=None,
                       build_wrapper_registry=None, allow_unpinned_wrapper=False,
                       track_b_baseline_hashes=None, track_b_baseline_registry=None,
                       allow_toy_baseline=False, bench_min_nps_ratio=None,
                       allow_no_bench=False, round_number=1, root=None,
                       games=None, movetime_ms=None, max_plies=None,
                       progress=lambda msg: None):
    """Run a hosted Track B evaluation. Returns (report dict, result_path)."""
    if root is None:
        root = paths.find_repo_root()
    out_dir = Path(out_dir)

    prof = get_profile("smoke") if quick_test_mode else get_profile(
        profile or PROFILE_OFFICIAL)

    # --- engine jail guard (P0.1) ---
    verified = False
    grade = prof.grade
    if prof.verifiable:
        if engine_jail == "docker":
            verified = True
        elif allow_unjailed:
            verified = False
            grade = GRADE_DIAGNOSTIC_UNJAILED
        else:
            raise TrackBPipelineError(
                "verified Track B %s evaluation requires --engine-jail docker; "
                "rerun with --engine-jail docker, or pass --dev-allow-unjailed "
                "for a diagnostic result" % prof.name)

    state = {"verified": verified, "grade": grade}

    def gate(ok, dev_allowed, fail_msg, downgrade_grade):
        """A trust gate. If ok, no-op. Else: downgrade (record the grade once)
        when its dev flag is set, otherwise hard-fail — but only while the run
        is still meant to be verified."""
        if ok or not state["verified"]:
            return
        if dev_allowed:
            state["grade"] = downgrade_grade
            state["verified"] = False
        else:
            raise TrackBPipelineError(fail_msg)

    trust = baseline_trust = wrapper = wrapper_hash = None
    build_isolation = "jail" if (prof.verifiable and engine_jail == "docker") \
        else "host"

    if prof.verifiable and engine_jail == "docker":
        if not eval_pack_dir:
            raise TrackBPipelineError(
                "verified Track B requires a private/official opening pack "
                "(--eval-pack)")

        # --- eval pack: official manifest, pinned hash, Ed25519 (req 1) ---
        allowed_pack = resolve_allowed_hashes(
            cli_hashes=official_pack_hashes, registry_path=official_pack_registry)
        try:
            trust = validate_official_eval_pack(
                eval_pack_dir, track="B", root=root, allowed_hashes=allowed_pack,
                allow_demo=allow_demo_pack)
        except EvalPackTrustError as exc:
            raise TrackBPipelineError(
                "official eval pack rejected: %s" % exc.public_message,
                "official eval pack rejected: %s" % private_detail(exc))
        gate(not trust.get("demo_path_allowed"), True,
             "demo pack cannot verify", GRADE_DIAGNOSTIC_UNTRUSTED_PACK)
        gate(trust.get("allowlist_checked"), allow_unpinned_pack,
             "verified Track B requires a PINNED official eval pack hash "
             "(--official-pack-hash / CEB_OFFICIAL_EVAL_PACK_HASHES); use "
             "--dev-allow-unpinned-pack for a diagnostic result",
             GRADE_DIAGNOSTIC_UNPINNED_PACK)
        gate(bool(ed25519_private_key_path(explicit_path=signing_key_path)),
             allow_unsigned,
             "verified Track B requires an Ed25519 signing key "
             "(CEB_SIGNING_PRIVATE_KEY / --signing-key); use "
             "--dev-allow-unsigned for a diagnostic result",
             GRADE_DIAGNOSTIC_UNSIGNED)
        if not state["verified"]:
            trust = None  # not a verified, trusted-pack claim

        # --- baseline trust (req 3) ---
        allowed_base = resolve_baseline_hashes(
            cli_hashes=track_b_baseline_hashes,
            registry_path=track_b_baseline_registry)
        try:
            baseline_trust = validate_track_b_baseline(
                baseline_src, root=root, allowed_hashes=allowed_base,
                allow_toy=True)  # never raise here; gate() decides
        except BaselineTrustError as exc:
            raise TrackBPipelineError(
                "Track B baseline rejected: %s" % exc.public_message)
        gate(baseline_trust["baseline_trusted"], allow_toy_baseline,
             "verified Track B requires a trusted baseline (pinned Stockfish "
             "checkout or --track-b-baseline-hash); use --dev-allow-toy-baseline "
             "for a diagnostic result", GRADE_DIAGNOSTIC_UNTRUSTED_BASELINE)

        # --- build wrapper: outside-tree + hash pin (req 4) ---
        # Only enforce the wrapper while the run is still meant to be verified.
        # A run already downgraded by an earlier anchor must NOT be hard-failed
        # here; it falls back to a host (diagnostic) build when no valid wrapper
        # is supplied (the engine still runs jailed for the match).
        from ceb.hosted.build_wrappers import (
            validate_build_wrapper, compute_wrapper_hash, resolve_wrapper_hashes,
            BuildWrapperError)
        if state["verified"]:
            try:
                wrapper = validate_build_wrapper(
                    build_wrapper, candidate_src=candidate_src,
                    baseline_src=baseline_src)
            except BuildWrapperError as exc:
                raise TrackBPipelineError(
                    "trusted build wrapper rejected: %s" % exc.public_message,
                    "build wrapper rejected: %s" % private_detail(exc))
            wrapper_hash = compute_wrapper_hash(wrapper)
            allowed_wrap = resolve_wrapper_hashes(
                cli_hashes=build_wrapper_hashes,
                registry_path=build_wrapper_registry)
            gate(bool(allowed_wrap) and wrapper_hash in allowed_wrap,
                 allow_unpinned_wrapper,
                 "verified Track B requires a PINNED build wrapper hash "
                 "(--build-wrapper-hash / CEB_TRACK_B_BUILD_WRAPPER_HASHES); use "
                 "--dev-allow-unpinned-wrapper for a diagnostic result",
                 GRADE_DIAGNOSTIC_UNTRUSTED_WRAPPER)
        # The unpinned-wrapper gate above (if it fires) keeps the (valid)
        # wrapper. If an EARLIER anchor downgraded the run, try the supplied
        # wrapper for an isolated diagnostic build, else fall back to host.
        if not state["verified"] and build_wrapper:
            try:
                wrapper = validate_build_wrapper(
                    build_wrapper, candidate_src=candidate_src,
                    baseline_src=baseline_src)
                wrapper_hash = compute_wrapper_hash(wrapper)
            except BuildWrapperError:
                wrapper = None

    verified = state["verified"]
    grade = state["grade"]
    # Build in the jail when we have a validated wrapper; otherwise a downgraded
    # diagnostic run uses the host build path.
    if prof.verifiable and engine_jail == "docker" and wrapper is not None:
        build_isolation = "jail"
    elif prof.verifiable and engine_jail == "docker":
        build_isolation = "host"  # downgraded diagnostic with no wrapper

    size = _MATCH_SIZE["diagnostic" if not prof.verifiable else prof.tier]
    g = games if games is not None else size[0]
    mt = movetime_ms if movetime_ms is not None else size[1]
    mp = max_plies if max_plies is not None else size[2]
    run_jail = engine_jail if prof.verifiable else "none"

    report = run_official_track_b(
        candidate_src=candidate_src, baseline_src=baseline_src,
        eval_pack_dir=eval_pack_dir, engine_jail=run_jail,
        build_script=build_script, engine_relpath=engine_relpath,
        games=g, movetime_ms=mt, max_plies=mp, run_id=run_id,
        round_number=round_number, runs_root=out_dir, root=root,
        verified=verified, profile=prof.name, verification_grade=grade,
        build_isolation=build_isolation,
        build_wrapper=str(wrapper) if wrapper else None,
        signing_key_path=signing_key_path, trust=trust,
        baseline_trust=baseline_trust, build_wrapper_hash=wrapper_hash,
        bench_min_nps_ratio=bench_min_nps_ratio, allow_no_bench=allow_no_bench,
        progress=progress)

    result_path = (out_dir / run_id / ("track_b_official_%d" % round_number)
                   / "official_result.json")
    return report, result_path


def track_b_score(report):
    """The leaderboard score for a Track B result: final delta Elo."""
    score = report.get("score") or {}
    return score.get("final_delta_elo", score.get("delta_elo"))


TRACK_B_RESULT_MODE = TRACK_B_OFFICIAL_MODE
