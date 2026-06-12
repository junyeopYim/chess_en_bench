"""Official evaluation: the only path that produces verified results.

Pipeline for one Track A submission:
  1. static anti-cheating scan of the snapshot (ceb.scan)
  2. strict gate against the private eval pack
  3. official round (or final eval) with the private pack, optionally with
     the engine jail
  4. public/private artifacts split (visibility manifest)
  5. reproducibility metadata + signing
  6. verified result recorded

The worker REFUSES to verify when the private eval pack is missing or the
strict gate fails. Self-reported local rounds never reach this code path
and are therefore never verified.
"""

import json
import time
from pathlib import Path

from ceb import paths
from ceb.eval_pack import resolve_eval_pack, EvalPackError
from ceb.hosted.metadata import build_metadata
from ceb.hosted.signing import sign_result
from ceb.rounds.round_runner import run_round, RoundError, MODE_OFFICIAL, MODE_FINAL
from ceb.sanitize import SanitizedError, private_detail, sanitize_exception
from ceb.scan import scan_workspace
from ceb.storage import (
    VISIBILITY_PRIVATE, VISIBILITY_PUBLIC, write_artifact,
)

# Tiny profile for toy/CI hosted evaluations (--quick-test-mode). Production
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


def run_official_eval(*, run_id, snapshot, eval_pack_dir, out_dir,
                      mode=MODE_OFFICIAL, round_number=1, engine_jail="none",
                      quick_test_mode=False, root=None,
                      progress=lambda msg: None):
    """Evaluate one snapshot officially. Returns the signed result dict.

    Raises OfficialEvalError (sanitized) when verification preconditions
    fail; nothing verified is written in that case.
    """
    if root is None:
        root = paths.find_repo_root()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot = Path(snapshot)
    if mode not in (MODE_OFFICIAL, MODE_FINAL):
        raise OfficialEvalError(
            "official evaluation runs only official_round or final_eval "
            "(got %r); quick rounds are never verified" % mode)

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

    progress("static scan ...")
    scan_report = scan_workspace(snapshot)
    write_artifact(out_dir, "scan_report.json", scan_report, VISIBILITY_PRIVATE)
    if not scan_report["passed"]:
        rules = sorted({f["rule"] for f in scan_report["findings"]
                        if f["severity"] == "fail"})
        raise OfficialEvalError(
            "static scan failed (%s); submission not eligible for official "
            "evaluation" % ", ".join(rules))

    progress("official %s (strict gate + matches) ..." % mode)
    try:
        round_report, feedback, state = run_round(
            snapshot, round_number, mode=mode, run_id=run_id,
            runs_root=out_dir, eval_pack_dir=eval_pack_dir,
            engine_jail=engine_jail,
            mode_config=QUICK_TEST_MODE_CONFIG if quick_test_mode else None,
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
        verified=True,
        cpu_cores=1,
        memory_limit="1g (engine jail)" if engine_jail == "docker" else None,
    )

    result = {
        "schema": "ceb.hosted.official_result/v1",
        "run_id": run_id,
        "track": "A",
        "mode": mode,
        "config_profile": "quick-test" if quick_test_mode else "configured",
        "round": round_number,
        "engine_jail": engine_jail,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "score": round_report["score"],
        "feedback": feedback,
        "metadata": metadata,
        "verified": True,
    }
    sign_result(result)
    write_artifact(out_dir, "official_result.json", result, VISIBILITY_PUBLIC)
    # Public copy of feedback at the top level for easy serving.
    write_artifact(out_dir, "feedback.json", feedback, VISIBILITY_PUBLIC)
    return result


def load_result(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
