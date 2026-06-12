"""FastAPI app: health, runs, leaderboard, artifacts, hosted endpoints.

Requires the 'server' extra:  pip install -e ".[server]"
Core gate/match/scoring never import this module.

Security model (v0.3):
  - hosted GET endpoints serve only artifacts whose DB-recorded visibility
    is "public"; everything else 404s (deny by default).
  - hosted POST endpoints are admin-only: they require the X-CEB-Admin-Token
    header to match the CEB_ADMIN_TOKEN env var; with no token configured
    they are disabled entirely (503).
  - results are explicitly marked verified/unverified; the hosted
    leaderboard contains verified results only.
"""

import json
import os
import re

try:
    from fastapi import FastAPI, Header, HTTPException
    from fastapi.responses import FileResponse, HTMLResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel
except ImportError as exc:  # pragma: no cover - exercised only without extras
    raise ImportError(
        "FastAPI is not installed. Install server extras with:\n"
        "  pip install -e \".[server]\"") from exc

from ceb import __version__, paths
from ceb.scoring.track_a import compute_leaderboard

app = FastAPI(title="chess_en_bench", version=__version__)

_ARTIFACT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

ADMIN_TOKEN_ENV = "CEB_ADMIN_TOKEN"
HOSTED_DB_ENV = "CEB_HOSTED_DB"


def _hosted_db_path():
    return os.environ.get(HOSTED_DB_ENV) or str(paths.runs_dir() / "hosted.sqlite")


def _hosted_conn():
    from ceb.hosted import db as hosted_db
    import sqlite3
    path = _hosted_db_path()
    if not os.path.isfile(path):
        raise HTTPException(status_code=503,
                            detail="hosted database not initialized "
                                   "(run: ceb hosted init)")
    try:
        return hosted_db.connect(path)
    except sqlite3.Error:  # pragma: no cover - disk-level failure
        raise HTTPException(status_code=503, detail="hosted database unavailable")


def _require_admin(token):
    configured = os.environ.get(ADMIN_TOKEN_ENV)
    if not configured:
        raise HTTPException(status_code=503,
                            detail="admin endpoints disabled (set %s)"
                                   % ADMIN_TOKEN_ENV)
    if not token or token != configured:
        raise HTTPException(status_code=403, detail="invalid admin token")


@app.get("/health")
def health():
    return {"status": "ok", "service": "chess_en_bench", "version": __version__}


@app.get("/api/runs")
def list_runs():
    runs = []
    runs_root = paths.runs_dir()
    for state_path in sorted(runs_root.glob("*/state.json")):
        try:
            runs.append(json.loads(state_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return {"runs": runs}


@app.get("/api/leaderboard")
def leaderboard(track: str = "A", include_quick: bool = False):
    """Official leaderboard (official rounds only). include_quick=true is a
    diagnostic view and must not be presented as an official ranking."""
    if track.upper() not in ("A", "B"):
        raise HTTPException(status_code=400, detail="track must be A or B")
    if track.upper() == "B":
        # Track B has no aggregated leaderboard yet; rounds are scored
        # individually via `ceb track-b round run`.
        return {"schema": "ceb.leaderboard/v1", "track": "B", "entries": [],
                "note": "Track B rounds are scored per run; see "
                        "docs/track_b_stockfish_optimization.md"}
    return compute_leaderboard(paths.runs_dir(), track="A",
                               include_quick=include_quick)


@app.get("/api/artifacts/{artifact_id}")
def get_artifact(artifact_id: str):
    """Resolve a flat artifact filename under artifacts/ (no path traversal)."""
    if not _ARTIFACT_ID_RE.match(artifact_id) or ".." in artifact_id:
        raise HTTPException(status_code=400, detail="bad artifact id")
    path = paths.artifacts_dir() / artifact_id
    if not path.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(path)


# ----- hosted endpoints (P0.8) ------------------------------------------------

class RunCreate(BaseModel):
    run_id: str
    track: str = "A"


class SubmissionCreate(BaseModel):
    workspace: str  # server-local path (MVP); uploads are future work


class JobCreate(BaseModel):
    kind: str = "official_eval"


@app.post("/api/hosted/runs")
def hosted_create_run(payload: RunCreate,
                      x_ceb_admin_token: str = Header(default=None)):
    _require_admin(x_ceb_admin_token)
    from ceb.hosted import db as hosted_db
    conn = _hosted_conn()
    try:
        if hosted_db.get_run(conn, payload.run_id):
            raise HTTPException(status_code=409, detail="run already exists")
        hosted_db.create_run(conn, payload.run_id, payload.track)
        return {"run_id": payload.run_id, "track": payload.track.upper(),
                "status": "created"}
    finally:
        conn.close()


@app.post("/api/hosted/runs/{run_id}/submissions")
def hosted_submit(run_id: str, payload: SubmissionCreate,
                  x_ceb_admin_token: str = Header(default=None)):
    _require_admin(x_ceb_admin_token)
    from ceb.hosted import db as hosted_db
    from ceb.hosted.submissions import snapshot_workspace, SubmissionError
    import time as _time
    conn = _hosted_conn()
    try:
        if not hosted_db.get_run(conn, run_id):
            raise HTTPException(status_code=404, detail="run not found")
        store = hosted_db.store_dir(_hosted_db_path())
        dest = store / run_id / "snapshots" / ("submission_%d" % int(_time.time()))
        try:
            snapshot, tree_hash = snapshot_workspace(payload.workspace, dest)
        except SubmissionError as exc:
            raise HTTPException(status_code=400, detail=exc.public_message)
        submission_id = hosted_db.add_submission(conn, run_id, snapshot, tree_hash)
        return {"submission_id": submission_id, "tree_hash": tree_hash}
    finally:
        conn.close()


@app.post("/api/hosted/runs/{run_id}/jobs")
def hosted_enqueue_job(run_id: str, payload: JobCreate,
                       x_ceb_admin_token: str = Header(default=None)):
    _require_admin(x_ceb_admin_token)
    from ceb.hosted import db as hosted_db
    from ceb.hosted.models import JOB_KINDS
    if payload.kind not in JOB_KINDS:
        raise HTTPException(status_code=400, detail="unknown job kind")
    conn = _hosted_conn()
    try:
        if not hosted_db.get_run(conn, run_id):
            raise HTTPException(status_code=404, detail="run not found")
        job_id = hosted_db.enqueue_job(conn, run_id, payload.kind)
        return {"job_id": job_id, "status": "queued"}
    finally:
        conn.close()


@app.get("/api/hosted/runs/{run_id}")
def hosted_run_info(run_id: str):
    from ceb.hosted import db as hosted_db
    conn = _hosted_conn()
    try:
        run = hosted_db.get_run(conn, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        results = hosted_db.results_for_run(conn, run_id)
        return {
            "run": run,
            "results": [
                {"id": r["id"], "mode": r["mode"],
                 "verified": bool(r["verified"]), "score": r["score"]}
                for r in results
            ],
        }
    finally:
        conn.close()


def _public_artifact_path(conn, run_id, name):
    """Resolve a public artifact for a run by artifact name suffix."""
    from ceb.hosted import db as hosted_db
    rows = conn.execute(
        "SELECT * FROM artifacts WHERE run_id = ? AND visibility = 'public'",
        (run_id,)).fetchall()
    for row in rows:
        if row["artifact_id"].endswith(name):
            return row["path"]
    return None


@app.get("/api/hosted/runs/{run_id}/feedback")
def hosted_feedback(run_id: str):
    conn = _hosted_conn()
    try:
        path = _public_artifact_path(conn, run_id, "feedback.json")
        if not path or not os.path.isfile(path):
            raise HTTPException(status_code=404, detail="no public feedback")
        return json.loads(open(path, encoding="utf-8").read())
    finally:
        conn.close()


@app.get("/api/hosted/runs/{run_id}/official-result")
def hosted_official_result(run_id: str):
    from ceb.hosted import db as hosted_db
    conn = _hosted_conn()
    try:
        results = hosted_db.results_for_run(conn, run_id, verified_only=True)
        if not results:
            raise HTTPException(status_code=404, detail="no verified result")
        best = results[-1]
        try:
            result = json.loads(open(best["result_path"], encoding="utf-8").read())
        except (OSError, ValueError):
            raise HTTPException(status_code=404, detail="result file unavailable")
        return result  # official_result.json is a public artifact by design
    finally:
        conn.close()


@app.get("/api/hosted/leaderboard")
def hosted_leaderboard(track: str = "A"):
    from ceb.hosted import db as hosted_db
    conn = _hosted_conn()
    try:
        return hosted_db.verified_leaderboard(conn, track=track)
    finally:
        conn.close()


@app.get("/api/hosted/artifacts/{artifact_id}")
def hosted_artifact(artifact_id: str):
    """Serve a PUBLIC hosted artifact. Private/admin/unknown -> 404."""
    from ceb.hosted import db as hosted_db
    if not _ARTIFACT_ID_RE.match(artifact_id) or ".." in artifact_id:
        raise HTTPException(status_code=400, detail="bad artifact id")
    conn = _hosted_conn()
    try:
        row = hosted_db.get_artifact(conn, artifact_id)
    finally:
        conn.close()
    # Deny by default: anything not explicitly public does not exist.
    if not row or row["visibility"] != "public":
        raise HTTPException(status_code=404, detail="artifact not found")
    store = hosted_db.store_dir(_hosted_db_path()).resolve()
    path = os.path.realpath(row["path"])
    if not path.startswith(str(store) + os.sep):
        raise HTTPException(status_code=404, detail="artifact not found")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(path)


_static = paths.web_static_dir()
if _static.is_dir():
    app.mount("/", StaticFiles(directory=str(_static), html=True), name="static")
else:  # pragma: no cover - repo always ships web/static
    @app.get("/", response_class=HTMLResponse)
    def index_fallback():
        return "<h1>chess_en_bench</h1><p>web/static not found.</p>"
