"""Hosted Track B official evaluation (P0.6 + v0.3.2 hardening).

Connects the source-first Track B pipeline to the hosted worker so Track B can
produce VERIFIED delta-Elo results. A verified Track B result requires, beyond
the source-first guarantees (diff whitelist + content scan):

  - a verifiable profile (official / final-production),
  - the docker engine jail confining the untrusted candidate engine (P0.1),
  - a TRUSTED official opening pack (A),
  - an Ed25519 signing key (B),
  - an isolated build in the Docker build jail using a trusted operator wrapper
    outside the candidate tree — never a candidate-owned host build (C),
  - a staged-then-promoted, leak-scanned public result (D).

A non-verifiable profile (smoke), --dev-allow-unjailed, or --dev-allow-unsigned
yields a diagnostic (verified=false) result that never reaches the leaderboard.
"""

from pathlib import Path

from ceb import paths
from ceb.hosted.eval_pack_trust import (
    resolve_allowed_hashes, validate_official_eval_pack, EvalPackTrustError)
from ceb.hosted.profiles import (
    PROFILE_OFFICIAL, GRADE_DIAGNOSTIC_UNJAILED, GRADE_DIAGNOSTIC_UNSIGNED,
    GRADE_DIAGNOSTIC_UNTRUSTED_PACK, TRACK_B_OFFICIAL_MODE, get_profile)
from ceb.hosted.signing import ed25519_private_key_path
from ceb.sanitize import private_detail
from ceb.track_b.official_pipeline import (
    run_official_track_b, TrackBPipelineError)

# Match sizes by tier: (games, movetime_ms, max_plies).
_MATCH_SIZE = {
    "diagnostic": (2, 30, 40),
    "official": (200, 200, 300),
    "final": (1000, 1000, 300),
}


def run_hosted_track_b(*, run_id, candidate_src, baseline_src, build_script,
                       engine_relpath, eval_pack_dir, out_dir, engine_jail,
                       profile=None, allow_unjailed=False, quick_test_mode=False,
                       official_pack_hashes=None, official_pack_registry=None,
                       allow_demo_pack=False, signing_key_path=None,
                       allow_unsigned=False, build_wrapper=None,
                       round_number=1, root=None, games=None, movetime_ms=None,
                       max_plies=None, progress=lambda msg: None):
    """Run a hosted Track B evaluation. Returns (report dict, result_path)."""
    if root is None:
        root = paths.find_repo_root()
    out_dir = Path(out_dir)

    prof = get_profile("smoke") if quick_test_mode else get_profile(
        profile or PROFILE_OFFICIAL)

    # Engine-jail guard (P0.1) for the untrusted candidate engine.
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
                "verified Track B %s evaluation requires --engine-jail docker "
                "(the untrusted candidate engine must run in the jail); rerun "
                "with --engine-jail docker, or pass --dev-allow-unjailed for a "
                "diagnostic (unverified) result" % prof.name)

    trust = None
    build_isolation = "host"
    wrapper = None
    if verified:
        if not eval_pack_dir:
            raise TrackBPipelineError(
                "verified Track B evaluation requires a private/official "
                "opening pack (--eval-pack)")
        allowed = resolve_allowed_hashes(cli_hashes=official_pack_hashes,
                                         registry_path=official_pack_registry)
        try:
            trust = validate_official_eval_pack(
                eval_pack_dir, track="B", root=root, allowed_hashes=allowed,
                allow_demo=allow_demo_pack)
        except EvalPackTrustError as exc:
            raise TrackBPipelineError(
                "official eval pack rejected: %s" % exc.public_message,
                "official eval pack rejected: %s" % private_detail(exc))
        if trust.get("demo_path_allowed"):
            verified = False
            grade = GRADE_DIAGNOSTIC_UNTRUSTED_PACK
            trust = None
        elif not ed25519_private_key_path(explicit_path=signing_key_path):
            if allow_unsigned:
                verified = False
                grade = GRADE_DIAGNOSTIC_UNSIGNED
                trust = None
            else:
                raise TrackBPipelineError(
                    "verified Track B requires an Ed25519 signing key (set "
                    "CEB_SIGNING_PRIVATE_KEY or pass --signing-key); HMAC is "
                    "not accepted. Use --dev-allow-unsigned for a diagnostic "
                    "result")

    if verified:
        from ceb.hosted.build_wrappers import (
            validate_build_wrapper, BuildWrapperError)
        try:
            wrapper = validate_build_wrapper(
                build_wrapper, candidate_src=candidate_src,
                baseline_src=baseline_src)
        except BuildWrapperError as exc:
            raise TrackBPipelineError(
                "trusted build wrapper rejected: %s" % exc.public_message,
                "build wrapper rejected: %s" % private_detail(exc))
        build_isolation = "jail"

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
        signing_key_path=signing_key_path, trust=trust, progress=progress)

    result_path = (out_dir / run_id / ("track_b_official_%d" % round_number)
                   / "official_result.json")
    return report, result_path


def track_b_score(report):
    """The leaderboard score for a Track B result: final delta Elo."""
    score = report.get("score") or {}
    return score.get("final_delta_elo", score.get("delta_elo"))


TRACK_B_RESULT_MODE = TRACK_B_OFFICIAL_MODE
