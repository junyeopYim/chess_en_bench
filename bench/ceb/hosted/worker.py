"""Official worker: drains queued jobs and produces verified results."""

from pathlib import Path

from ceb.hosted import db as hosted_db
from ceb.hosted.official_eval import run_official_eval, OfficialEvalError
from ceb.rounds.round_runner import MODE_OFFICIAL
from ceb.sanitize import private_detail, sanitize_exception
from ceb.storage import VISIBILITY_PUBLIC, VISIBILITY_PRIVATE, visibility_of


def run_once(db_path, *, eval_pack_dir=None, engine_jail="none",
             quick_test_mode=False, mode=MODE_OFFICIAL,
             progress=lambda msg: None):
    """Process the oldest queued job. Returns a status dict.

    {"status": "idle"} when the queue is empty;
    {"status": "done", ...} on success;
    {"status": "failed", ...} with a sanitized reason on failure.
    """
    conn = hosted_db.connect(db_path)
    try:
        job = hosted_db.next_queued_job(conn)
        if job is None:
            return {"status": "idle", "detail": "no queued jobs"}
        run_id = job["run_id"]
        progress("job %d: %s for run %s" % (job["id"], job["kind"], run_id))
        submission = hosted_db.latest_submission(conn, run_id)
        if submission is None:
            hosted_db.finish_job(conn, job["id"], "failed", "no submission")
            return {"status": "failed", "job_id": job["id"],
                    "detail": "run has no submission snapshot"}

        out_dir = hosted_db.store_dir(db_path) / run_id / ("job_%d" % job["id"])
        try:
            result = run_official_eval(
                run_id=run_id,
                snapshot=submission["snapshot_path"],
                eval_pack_dir=eval_pack_dir,
                out_dir=out_dir,
                mode=mode,
                engine_jail=engine_jail,
                quick_test_mode=quick_test_mode,
                progress=progress,
            )
        except OfficialEvalError as exc:
            hosted_db.finish_job(conn, job["id"], "failed", private_detail(exc))
            return {"status": "failed", "job_id": job["id"],
                    "detail": sanitize_exception(exc)}
        except Exception as exc:  # noqa: BLE001 - worker must not crash the queue
            hosted_db.finish_job(conn, job["id"], "failed", private_detail(exc))
            return {"status": "failed", "job_id": job["id"],
                    "detail": sanitize_exception(exc)}

        result_path = Path(out_dir) / "official_result.json"
        hosted_db.add_result(
            conn, run_id, job["id"], verified=True, mode=result["mode"],
            score=result["score"]["final_score"], result_path=result_path)
        _register_artifacts(conn, run_id, out_dir, db_path)
        hosted_db.finish_job(conn, job["id"], "done")
        return {"status": "done", "job_id": job["id"], "run_id": run_id,
                "result_path": str(result_path),
                "final_score": result["score"]["final_score"],
                "verified": True}
    finally:
        conn.close()


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
