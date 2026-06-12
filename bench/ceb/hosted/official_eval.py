"""Official evaluation: the only path that produces verified results.

Pipeline for one Track A submission (v0.3.2):
  1. require a private eval pack (refuse to verify on public data only)
  2. engine-jail guard: a verifiable profile must run in the docker engine jail
     (P0.1) unless an explicit dev flag downgrades the result to diagnostic
  3. trusted official eval-pack guard: a verified result requires an OFFICIAL
     pack (manifest + non-demo path + optional hash allowlist); the committed
     demo pack can never verify
  4. Ed25519 signing guard: a verified result requires an Ed25519 private key
  5. static anti-cheating scan of the snapshot
  6. strict gate + matches against the private pack, in the engine jail
  7. public artifacts written STAGED (private) — never public before scanning
  8. public-artifact leak scan over the staged set; refuse on any leak
  9. reproducibility metadata + Ed25519 signature
 10. atomic promotion of the staged artifacts to public, then the worker records
     a verified result

The worker REFUSES to verify when the pack is missing/untrusted, the engine
jail is not docker, no Ed25519 key is configured, the scan or strict gate
fails, or a leak is detected. Self-reported local rounds never reach this code
path and are therefore never verified.
"""

import json
import time
from pathlib import Path

from ceb import paths
from ceb.eval_pack import resolve_eval_pack, EvalPackError
from ceb.hosted.eval_pack_trust import (
    resolve_allowed_hashes, validate_official_eval_pack, EvalPackTrustError)
from ceb.hosted.metadata import build_metadata
from ceb.hosted.models import SCHEMA_OFFICIAL_RESULT
from ceb.hosted.profiles import (
    PROFILE_OFFICIAL, GRADE_DIAGNOSTIC_UNJAILED, GRADE_DIAGNOSTIC_UNSIGNED,
    GRADE_DIAGNOSTIC_UNTRUSTED_PACK, GRADE_DIAGNOSTIC_UNPINNED_PACK,
    get_profile, profile_for_mode)
from ceb.hosted.signing import (
    ALGORITHM_ED25519, require_ed25519_private_key, sign_official_result,
    SigningError)
from ceb.rounds.round_runner import run_round, RoundError
from ceb.sanitize import SanitizedError, private_detail, sanitize_exception
from ceb.scan import scan_workspace, scan_public_artifacts
from ceb.storage import VISIBILITY_PRIVATE, write_artifact
from ceb.storage.promotion import (
    promote_public_artifacts, write_staged_public_artifact)

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
                      official_pack_hashes=None, official_pack_registry=None,
                      allow_demo_pack=False, allow_unpinned_pack=False,
                      signing_key_path=None, allow_unsigned=False,
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

    if run_jail == "docker":
        from ceb.jail import docker_engine
        try:
            docker_engine.ensure_ready()
        except docker_engine.DockerJailError as exc:
            raise OfficialEvalError("engine jail not ready: %s" % exc)

    # Trusted-pack guard (A) + Ed25519 guard (B) apply only to a result that
    # would be verified. Both fail BEFORE any evaluation work.
    trust = None
    if verified:
        allowed = resolve_allowed_hashes(cli_hashes=official_pack_hashes,
                                         registry_path=official_pack_registry)
        try:
            trust = validate_official_eval_pack(
                eval_pack_dir, track="A", root=root, allowed_hashes=allowed,
                allow_demo=allow_demo_pack)
        except EvalPackTrustError as exc:
            raise OfficialEvalError(
                "official eval pack rejected: %s" % exc.public_message,
                "official eval pack rejected: %s" % private_detail(exc))
        if trust.get("demo_path_allowed"):
            # The pack only passed because --dev-allow-demo-pack bypassed the
            # committed/demo path check: this is a diagnostic, never verified.
            verified = False
            grade = GRADE_DIAGNOSTIC_UNTRUSTED_PACK
            trust = None
        elif not trust.get("allowlist_checked"):
            # Public official verification requires the pack hash to be PINNED.
            if allow_unpinned_pack:
                verified = False
                grade = GRADE_DIAGNOSTIC_UNPINNED_PACK
                trust = None
            else:
                raise OfficialEvalError(
                    "verified %s evaluation requires a PINNED official eval "
                    "pack hash (--official-pack-hash / "
                    "CEB_OFFICIAL_EVAL_PACK_HASHES / --official-pack-registry); "
                    "use --dev-allow-unpinned-pack for a diagnostic result"
                    % prof.name)
        else:
            # Pack is trusted + pinned: LOAD-validate the Ed25519 key now, before
            # any scan/gate/match, so a signing failure cannot strand work.
            try:
                key_path = require_ed25519_private_key(explicit_path=signing_key_path)
            except SigningError as exc:
                raise OfficialEvalError(
                    "Ed25519 signing key could not be loaded; refusing to "
                    "evaluate", "Ed25519 key load failed: %s" % exc)
            if not key_path:
                if allow_unsigned:
                    verified = False
                    grade = GRADE_DIAGNOSTIC_UNSIGNED
                    trust = None
                else:
                    raise OfficialEvalError(
                        "verified %s evaluation requires an Ed25519 signing key "
                        "(set CEB_SIGNING_PRIVATE_KEY or pass --signing-key); "
                        "HMAC is not accepted for public official results. Use "
                        "--dev-allow-unsigned for a diagnostic result" % prof.name)
            else:
                signing_key_path = key_path  # validated; reused at signing time

    progress("static scan ...")
    scan_report = scan_workspace(snapshot)
    write_artifact(out_dir, "scan_report.json", scan_report, VISIBILITY_PRIVATE)
    if not scan_report["passed"]:
        rules = sorted({f["rule"] for f in scan_report["findings"]
                        if f["severity"] == "fail"})
        raise OfficialEvalError(
            "static scan failed (%s); submission not eligible for official "
            "evaluation" % ", ".join(rules))

    effective_config = QUICK_TEST_MODE_CONFIG if prof.tiny_config else None
    if mode_config is not None:
        effective_config = mode_config

    progress("official %s (strict gate + matches) ..." % eval_mode)
    try:
        round_report, feedback, state = run_round(
            snapshot, round_number, mode=eval_mode, run_id=run_id,
            runs_root=out_dir, eval_pack_dir=eval_pack_dir,
            engine_jail=run_jail, mode_config=effective_config,
            stage_public=True, progress=progress, root=root)
    except RoundError as exc:
        raise OfficialEvalError(
            "official evaluation failed: %s" % sanitize_exception(exc),
            "official evaluation failed: %s" % exc)

    pack = resolve_eval_pack(root, private_dir=eval_pack_dir)
    metadata = build_metadata(
        root=root, eval_pack_dir=eval_pack_dir, eval_pack_id=pack.name,
        opening_suite=pack.openings, random_seed=1000 * round_number,
        verified=verified, cpu_cores=1,
        memory_limit="1g (engine jail)" if run_jail == "docker" else None)
    metadata["eval_pack_trusted"] = bool(verified and trust)
    metadata["eval_pack_manifest_hash"] = trust["manifest_hash"] if trust else None
    metadata["eval_pack_track"] = trust["track"] if trust else None
    metadata["eval_pack_season"] = trust["season"] if trust else None
    if trust:
        metadata["eval_pack_id"] = trust["pack_id"]

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
    sign_official_result(result, private_key_path=signing_key_path)
    # Defense in depth: a verified result MUST be Ed25519-signed.
    if verified and result["signature"].get("algorithm") != ALGORITHM_ED25519:
        raise OfficialEvalError(
            "internal error: verified result is not Ed25519-signed; refusing")

    # Stage the top-level public artifacts (private until promoted).
    write_staged_public_artifact(out_dir, "official_result.json", result)
    write_staged_public_artifact(out_dir, "feedback.json", feedback)

    # Leak-scan the STAGED public surface BEFORE anything becomes public.
    leak_report = scan_public_artifacts(out_dir, eval_pack_dir, root, staged=True)
    write_artifact(out_dir, "leak_scan.json", leak_report, VISIBILITY_PRIVATE)
    if not leak_report["passed"]:
        raise OfficialEvalError(
            "public artifact leak scan failed: a hidden eval-pack secret would "
            "have been exposed in a public artifact; verification refused",
            "public artifact leak scan failed: %s" % json.dumps(leak_report))

    # Only now promote the staged artifacts to public.
    promote_public_artifacts(out_dir)
    return result


def load_result(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
