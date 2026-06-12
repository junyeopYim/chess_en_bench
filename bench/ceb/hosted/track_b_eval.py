"""Hosted Track B official evaluation (P0.6, Option A).

Connects the source-first Track B pipeline to the hosted worker so Track B can
produce VERIFIED delta-Elo results on the hosted leaderboard. A verified Track
B result requires, in addition to the source-first pipeline's own guarantees
(diff whitelist + content scan + identical build script for baseline and
candidate):

  - a verifiable profile (official / final-production),
  - the docker engine jail confining the untrusted candidate engine (P0.1),
  - a private/official opening pack (refuse to verify on public openings only),
  - a public-artifact leak scan pass (P0.8), and
  - a signed result.

A non-verifiable profile (smoke) or the --dev-allow-unjailed escape hatch
yields a diagnostic (verified=false) result that never reaches the leaderboard.
Per-profile match sizes keep CI fast (smoke) while production runs play enough
games for a meaningful confidence interval.
"""

from pathlib import Path

from ceb import paths
from ceb.hosted.models import SCHEMA_TRACK_B_RESULT
from ceb.hosted.profiles import (
    PROFILE_OFFICIAL, GRADE_DIAGNOSTIC_UNJAILED, TRACK_B_OFFICIAL_MODE,
    get_profile)
from ceb.track_b.official_pipeline import (
    run_official_track_b, TrackBPipelineError)

# Match sizes by profile tier. Production plays enough games for a tight CI;
# smoke is tiny for CI/plumbing. (games, movetime_ms, max_plies)
_MATCH_SIZE = {
    "diagnostic": (2, 30, 40),
    "official": (200, 200, 300),
    "final": (1000, 1000, 300),
}


def run_hosted_track_b(*, run_id, candidate_src, baseline_src, build_script,
                       engine_relpath, eval_pack_dir, out_dir, engine_jail,
                       profile=None, allow_unjailed=False, quick_test_mode=False,
                       round_number=1, root=None, games=None, movetime_ms=None,
                       max_plies=None, progress=lambda msg: None):
    """Run a hosted Track B evaluation. Returns (report dict, result_path).

    Raises TrackBPipelineError (sanitized) when verification preconditions fail.
    """
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

    # Verified Track B requires a private/official opening pack, like Track A.
    if verified and not eval_pack_dir:
        raise TrackBPipelineError(
            "verified Track B evaluation requires a private/official opening "
            "pack (--eval-pack); refusing to verify on public openings only")

    # Smoke is plumbing and runs unjailed regardless of the flag.
    run_jail = engine_jail if prof.verifiable else "none"
    size = _MATCH_SIZE["diagnostic" if not prof.verifiable else prof.tier]
    g = games if games is not None else size[0]
    mt = movetime_ms if movetime_ms is not None else size[1]
    mp = max_plies if max_plies is not None else size[2]

    report = run_official_track_b(
        candidate_src=candidate_src, baseline_src=baseline_src,
        eval_pack_dir=eval_pack_dir, engine_jail=run_jail,
        build_script=build_script, engine_relpath=engine_relpath,
        games=g, movetime_ms=mt, max_plies=mp, run_id=run_id,
        round_number=round_number, runs_root=out_dir, root=root,
        verified=verified, profile=prof.name, verification_grade=grade,
        progress=progress)

    result_path = (out_dir / run_id / ("track_b_official_%d" % round_number)
                   / "official_result.json")
    return report, result_path


def track_b_score(report):
    """The leaderboard score for a Track B result: final delta Elo."""
    score = report.get("score") or {}
    return score.get("final_delta_elo", score.get("delta_elo"))


TRACK_B_RESULT_MODE = TRACK_B_OFFICIAL_MODE
