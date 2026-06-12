"""Official evaluation: the only path that produces verified results.

Pipeline for one Track A submission:
  1. require a private eval pack (refuse to verify on public data only)
  2. engine-jail guard: a verifiable profile must run in the docker engine jail
     (P0.1) unless an explicit dev flag downgrades the result to diagnostic
  3. static anti-cheating scan of the snapshot (ceb.scan)
  4. strict gate against the private eval pack
  5. official round / final eval with the private pack, in the engine jail
  6. public/private artifacts split (visibility manifest)
  7. public-artifact leak scan (P0.8): refuse to verify if any hidden pack
     secret would be exposed
  8. reproducibility metadata + signing (Ed25519 > HMAC > unsigned)
  9. verified result recorded — only when the profile is verifiable AND every
     gate above passed AND the engine jail was docker

The worker REFUSES to verify when the private eval pack is missing, the scan
fails, the strict gate fails, a leak is detected, or the engine jail is not
docker. Self-reported local rounds never reach this code path and are
therefore never verified.
"""

import json
import time
from pathlib import Path

from ceb import paths
from ceb.eval_pack import resolve_eval_pack, EvalPackError
from ceb.hosted.metadata import build_metadata
from ceb.hosted.models import SCHEMA_OFFICIAL_RESULT
from ceb.hosted.profiles import (
    PROFILE_OFFICIAL, GRADE_DIAGNOSTIC_UNJAILED, get_profile, profile_for_mode)
from ceb.hosted.signing import sign_official_result
from ceb.rounds.round_runner import run_round, RoundError
from ceb.sanitize import SanitizedError, private_detail, sanitize_exception
from ceb.scan import scan_workspace, scan_public_artifacts
from ceb.storage import VISIBILITY_PRIVATE, VISIBILITY_PUBLIC, write_artifact

# Tiny profile for toy/CI hosted evaluations (the `smoke` profile). Production
# uses the configured round modes from tracks/a_from_scratch/scoring.yaml.
QUICK_TEST_MODE_CONFIG = {
    "opponents": ["BenchRandom"],
    "games_per_opponent": 2,
    "movetime_ms": 30,
    "max_plies": 30,
    "openings_limit": 1,
}


class OfficialEvalError(SanitizedError, RuntimeError):
    pass


def _resolve_profile(profile, mode, quick_test_mode):
    if quick_test_mode:
        return get_profile("smoke")
    if profile is not None:
        return profile if hasattr(profile, "verifiable") else get_profile(profile)
    if mode is not None:
        return profile_for_mode(mode)
    return get_profile(PROFILE_OFFICIAL)


def run_official_eval(*, run_id, snapshot, eval_pack_dir, out_dir,
                      profile=None, engine_jail="docker", allow_unjailed=False,
                      round_number=1, root=None, progress=lambda msg: None,
                      mode=None, quick_test_mode=False, mode_config=None):
    """Evaluate one snapshot. Returns the signed result dict.

    Raises OfficialEvalError (sanitized) when verification preconditions fail;
    nothing verified is written in that case.
    """
    if root is None:
        root = paths.find_repo_root()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot = Path(snapshot)

    prof = _resolve_profile(profile, mode, quick_test_mode)
    eval_mode = prof.mode

    # Official mode REQUIRES a private eval pack.
    if not eval_pack_dir:
        raise OfficialEvalError(
            "official evaluation requires a private eval pack "
            "(--eval-pack or CEB_PRIVATE_EVAL_DIR); refusing to verify "
            "against public data only")
    try:
        resolve_eval_pack(root, private_dir=eval_pack_dir)
    except EvalPackError as exc:
        raise OfficialEvalError(
            "eval pack rejected: %s" % exc.public_message,
            "eval pack rejected: %s" % private_detail(exc))

    # Engine-jail guard (P0.1): a verifiable profile MUST run jailed to be
    # verified. Fail before any evaluation when the jail is missing, unless the
    # operator explicitly downgrades the result to a diagnostic (unverified).
    # A non-verifiable profile (smoke) is plumbing and runs unjailed regardless
    # of the flag, so CI never needs docker.
    verified = False
    grade = prof.grade
    if prof.verifiable:
        if engine_jail == "docker":
            verified = True
        elif allow_unjailed:
            verified = False
            grade = GRADE_DIAGNOSTIC_UNJAILED
        else:
            raise OfficialEvalError(
                "verified %s evaluation requires --engine-jail docker (the "
                "untrusted engine must run in the jail); rerun with "
                "--engine-jail docker, or pass --dev-allow-unjailed for a "
                "diagnostic (unverified) result" % prof.name)
    run_jail = engine_jail if prof.verifiable else "none"

    # Fail fast with an actionable message if the docker jail is required but
    # the daemon/image is missing — before any evaluation work.
    if run_jail == "docker":
        from ceb.jail import docker_engine
        try:
            docker_engine.ensure_ready()
        except docker_engine.DockerJailError as exc:
            raise OfficialEvalError("engine jail not ready: %s" % exc)

    progress("static scan ...")
    scan_report = scan_workspace(snapshot)
    write_artifact(out_dir, "scan_report.json", scan_report, VISIBILITY_PRIVATE)
    if not scan_report["passed"]:
        rules = sorted({f["rule"] for f in scan_report["findings"]
                        if f["severity"] == "fail"})
        raise OfficialEvalError(
            "static scan failed (%s); submission not eligible for official "
            "evaluation" % ", ".join(rules))

    # Match config: the profile's (tiny for smoke, configured otherwise). An
    # explicit mode_config override is an operator/testing knob (mirrors
    # run_round) so the unjailed/diagnostic path can be exercised quickly.
    effective_config = QUICK_TEST_MODE_CONFIG if prof.tiny_config else None
    if mode_config is not None:
        effective_config = mode_config

    progress("official %s (strict gate + matches) ..." % eval_mode)
    try:
        round_report, feedback, state = run_round(
            snapshot, round_number, mode=eval_mode, run_id=run_id,
            runs_root=out_dir, eval_pack_dir=eval_pack_dir,
            engine_jail=run_jail, mode_config=effective_config,
            progress=progress, root=root)
    except RoundError as exc:
        raise OfficialEvalError(
            "official evaluation failed: %s" % sanitize_exception(exc),
            "official evaluation failed: %s" % exc)

    pack = resolve_eval_pack(root, private_dir=eval_pack_dir)
    seed = 1000 * round_number
    metadata = build_metadata(
        root=root,
        eval_pack_dir=eval_pack_dir,
        eval_pack_id=pack.name,
        opening_suite=pack.openings,
        random_seed=seed,
        verified=verified,
        cpu_cores=1,
        memory_limit="1g (engine jail)" if run_jail == "docker" else None,
    )

    result = {
        "schema": SCHEMA_OFFICIAL_RESULT,
        "run_id": run_id,
        "track": "A",
        "mode": eval_mode,
        "profile": prof.name,
        "verification_grade": grade,
        "config_profile": "quick-test" if prof.tiny_config else "configured",
        "round": round_number,
        "engine_jail": run_jail,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "score": round_report["score"],
        "feedback": feedback,
        "metadata": metadata,
        "verified": verified,
    }
    sign_official_result(result)
    write_artifact(out_dir, "official_result.json", result, VISIBILITY_PUBLIC)
    # Public copy of feedback at the top level for easy serving.
    write_artifact(out_dir, "feedback.json", feedback, VISIBILITY_PUBLIC)

    # Public-artifact leak scan (P0.8): refuse to verify if any hidden pack
    # secret would reach a public artifact. The report is private and never
    # echoes the secret itself.
    leak_report = scan_public_artifacts(out_dir, eval_pack_dir, root)
    write_artifact(out_dir, "leak_scan.json", leak_report, VISIBILITY_PRIVATE)
    if not leak_report["passed"]:
        raise OfficialEvalError(
            "public artifact leak scan failed: a hidden eval-pack secret would "
            "have been exposed in a public artifact; verification refused",
            "public artifact leak scan failed: %s" % json.dumps(leak_report))

    return result


def load_result(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
