"""Official worker: atomically claims queued jobs and produces results.

Only this code can record `verified: true`, and only when the evaluation
profile is verifiable AND every gate passes (private pack, scan, strict gate,
engine jail = docker, leak scan, signature). Jobs are claimed atomically
(ceb.hosted.db.claim_next_job) so multiple workers can run safely, and the
result is recorded under an ownership fence (record_result_if_owned) so a
stale worker whose lease was reclaimed can never write a duplicate result.
"""

from pathlib import Path

from ceb.hosted import db as hosted_db
from ceb.hosted.models import JOB_KIND_TRACK_B
from ceb.hosted.official_eval import run_official_eval, OfficialEvalError
from ceb.hosted.profiles import TRACK_B_OFFICIAL_MODE
from ceb.hosted.track_b_eval import run_hosted_track_b
from ceb.sanitize import private_detail, sanitize_exception, SanitizedError
from ceb.storage import VISIBILITY_PRIVATE, visibility_of


def run_once(db_path, *, eval_pack_dir=None, engine_jail="none",
             profile=None, quick_test_mode=False, allow_unjailed=False,
             worker_id=None, lease_seconds=None, mode=None,
             progress=lambda msg: None):
    """Atomically claim and process the oldest queued job. Returns a status dict.

    {"status": "idle"} when nothing is claimable;
    {"status": "done", ...} on success;
    {"status": "failed", ...} with a sanitized reason on failure;
    {"status": "superseded", ...} if this worker's claim was reclaimed while it
    was evaluating (its result is discarded — no duplicate).

    engine_jail defaults to "none" here for programmatic/smoke callers; the CLI
    defaults it to "docker". A verifiable profile still refuses to verify
    without the docker jail (see ceb.hosted.official_eval).
    """
    conn = hosted_db.connect(db_path)
    try:
        job = hosted_db.claim_next_job(conn, worker_id=worker_id,
                                       lease_seconds=lease_seconds)
        if job is None:
            return {"status": "idle", "detail": "no claimable jobs"}
        run_id = job["run_id"]
        progress("claimed job %d (%s) for run %s [worker=%s attempt=%d]"
                 % (job["id"], job["kind"], run_id, worker_id or "-",
                    job.get("attempt_count", 1)))
        # Attempt-keyed output dir so a reclaiming worker never collides on disk
        # with the stale worker it superseded.
        out_dir = (hosted_db.store_dir(db_path) / run_id
                   / ("job_%d_attempt_%d" % (job["id"],
                                             job.get("attempt_count", 1))))

        # 1. Evaluate (writes artifacts to out_dir; NO DB result row yet).
        try:
            if job["kind"] == JOB_KIND_TRACK_B:
                record = _evaluate_track_b(
                    conn, job, out_dir, eval_pack_dir=eval_pack_dir,
                    engine_jail=engine_jail, profile=profile,
                    quick_test_mode=quick_test_mode,
                    allow_unjailed=allow_unjailed, progress=progress)
            else:
                record = _evaluate_track_a(
                    conn, job, out_dir, eval_pack_dir=eval_pack_dir,
                    engine_jail=engine_jail, profile=profile,
                    quick_test_mode=quick_test_mode,
                    allow_unjailed=allow_unjailed, mode=mode, progress=progress)
        except Exception as exc:  # noqa: BLE001 - worker must not crash the queue
            hosted_db.finish_job_if_owned(
                conn, job, "failed", detail=private_detail(exc),
                public_detail=sanitize_exception(exc))
            return {"status": "failed", "job_id": job["id"],
                    "detail": sanitize_exception(exc)}

        # 2. Record the result + mark done ATOMICALLY, only if still owned.
        result_id = hosted_db.record_result_if_owned(
            conn, job, verified=record["verified"], mode=record["mode"],
            score=record["score"], result_path=record["result_path"],
            profile=record["profile"],
            verification_grade=record["verification_grade"],
            track=record["track"])
        if result_id is None:
            return {"status": "superseded", "job_id": job["id"], "run_id": run_id,
                    "detail": "claim was reclaimed by another worker; result "
                              "discarded (no duplicate recorded)"}

        # 3. Register artifacts for API serving (only after we won the record).
        _register_artifacts(conn, run_id, out_dir, db_path)
        outcome = dict(record["outcome"])
        outcome["result_id"] = result_id
        return outcome
    finally:
        conn.close()


def _evaluate_track_a(conn, job, out_dir, *, eval_pack_dir, engine_jail,
                      profile, quick_test_mode, allow_unjailed, mode, progress):
    run_id = job["run_id"]
    submission = hosted_db.latest_submission(conn, run_id)
    if submission is None:
        raise OfficialEvalError("run has no submission snapshot")
    result = run_official_eval(
        run_id=run_id, snapshot=submission["snapshot_path"],
        eval_pack_dir=eval_pack_dir, out_dir=out_dir, profile=profile,
        engine_jail=engine_jail, allow_unjailed=allow_unjailed,
        quick_test_mode=quick_test_mode, mode=mode, progress=progress)
    result_path = Path(out_dir) / "official_result.json"
    return {
        "verified": result["verified"], "mode": result["mode"],
        "score": result["score"]["final_score"], "result_path": result_path,
        "profile": result["profile"],
        "verification_grade": result["verification_grade"], "track": "A",
        "outcome": {"status": "done", "job_id": job["id"], "run_id": run_id,
                    "track": "A", "result_path": str(result_path),
                    "final_score": result["score"]["final_score"],
                    "verified": result["verified"], "profile": result["profile"],
                    "verification_grade": result["verification_grade"]},
    }


def _evaluate_track_b(conn, job, out_dir, *, eval_pack_dir, engine_jail,
                      profile, quick_test_mode, allow_unjailed, progress):
    from ceb.hosted.track_b_eval import track_b_score

    run_id = job["run_id"]
    submission = hosted_db.latest_track_b_submission(conn, run_id)
    if submission is None:
        raise _TrackBJobError("run has no Track B submission snapshot")
    report, result_path = run_hosted_track_b(
        run_id=run_id,
        candidate_src=submission["candidate_snapshot"],
        baseline_src=submission["baseline_snapshot"],
        build_script=submission["build_script"],
        engine_relpath=submission["engine_relpath"],
        eval_pack_dir=eval_pack_dir, out_dir=out_dir, engine_jail=engine_jail,
        profile=profile, allow_unjailed=allow_unjailed,
        quick_test_mode=quick_test_mode, progress=progress)
    score = track_b_score(report)
    return {
        "verified": report["verified"], "mode": TRACK_B_OFFICIAL_MODE,
        "score": score, "result_path": result_path,
        "profile": report.get("profile"),
        "verification_grade": report.get("verification_grade"), "track": "B",
        "outcome": {"status": "done", "job_id": job["id"], "run_id": run_id,
                    "track": "B", "result_path": str(result_path),
                    "delta_elo": score, "verified": report["verified"],
                    "profile": report.get("profile"),
                    "verification_grade": report.get("verification_grade")},
    }


class _TrackBJobError(SanitizedError, RuntimeError):
    pass


def _register_artifacts(conn, run_id, out_dir, db_path):
    """Record artifact visibility in the DB for API serving."""
    store = hosted_db.store_dir(db_path)
    for path in sorted(Path(out_dir).rglob("*")):
        if not path.is_file():
            continue
        visibility = visibility_of(path.parent, path.name)
        if visibility is None:
            visibility = VISIBILITY_PRIVATE  # deny by default
        artifact_id = "%s_%s" % (run_id, path.relative_to(store / run_id)
                                 .as_posix().replace("/", "_"))
        hosted_db.register_artifact(conn, artifact_id, run_id, path, visibility)
