"""SQLite backend for the hosted pipeline.

Tables: runs, submissions, jobs, results. Results carry `verified` —
true only when produced by the official worker (ceb.hosted.worker).
"""

import json
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    track TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'created',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    snapshot_path TEXT NOT NULL,
    tree_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    detail TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    job_id INTEGER REFERENCES jobs(id),
    verified INTEGER NOT NULL DEFAULT 0,
    mode TEXT,
    score REAL,
    result_path TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    path TEXT NOT NULL,
    visibility TEXT NOT NULL
);
"""


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def connect(db_path):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path):
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
    return Path(db_path)


def store_dir(db_path):
    """Object-store directory next to the database file."""
    db_path = Path(db_path)
    store = db_path.parent / (db_path.stem + "_store")
    store.mkdir(parents=True, exist_ok=True)
    return store


def create_run(conn, run_id, track):
    conn.execute(
        "INSERT INTO runs (run_id, track, status, created_at) VALUES (?,?,?,?)",
        (run_id, track.upper(), "created", _now()))
    conn.commit()


def get_run(conn, run_id):
    row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def add_submission(conn, run_id, snapshot_path, tree_hash):
    cur = conn.execute(
        "INSERT INTO submissions (run_id, snapshot_path, tree_hash, created_at) "
        "VALUES (?,?,?,?)", (run_id, str(snapshot_path), tree_hash, _now()))
    conn.commit()
    return cur.lastrowid


def latest_submission(conn, run_id):
    row = conn.execute(
        "SELECT * FROM submissions WHERE run_id = ? ORDER BY id DESC LIMIT 1",
        (run_id,)).fetchone()
    return dict(row) if row else None


def enqueue_job(conn, run_id, kind):
    cur = conn.execute(
        "INSERT INTO jobs (run_id, kind, status, created_at) VALUES (?,?,?,?)",
        (run_id, kind, "queued", _now()))
    conn.commit()
    return cur.lastrowid


def next_queued_job(conn):
    row = conn.execute(
        "SELECT * FROM jobs WHERE status = 'queued' ORDER BY id LIMIT 1").fetchone()
    return dict(row) if row else None


def finish_job(conn, job_id, status, detail=None):
    conn.execute(
        "UPDATE jobs SET status = ?, detail = ?, finished_at = ? WHERE id = ?",
        (status, detail, _now(), job_id))
    conn.commit()


def add_result(conn, run_id, job_id, *, verified, mode, score, result_path):
    cur = conn.execute(
        "INSERT INTO results (run_id, job_id, verified, mode, score, "
        "result_path, created_at) VALUES (?,?,?,?,?,?,?)",
        (run_id, job_id, 1 if verified else 0, mode, score,
         str(result_path), _now()))
    conn.commit()
    return cur.lastrowid


def results_for_run(conn, run_id, verified_only=False):
    query = "SELECT * FROM results WHERE run_id = ?"
    if verified_only:
        query += " AND verified = 1"
    return [dict(r) for r in conn.execute(query + " ORDER BY id", (run_id,))]


def register_artifact(conn, artifact_id, run_id, path, visibility):
    conn.execute(
        "INSERT OR REPLACE INTO artifacts (artifact_id, run_id, path, visibility) "
        "VALUES (?,?,?,?)", (artifact_id, run_id, str(path), visibility))
    conn.commit()


def get_artifact(conn, artifact_id):
    row = conn.execute("SELECT * FROM artifacts WHERE artifact_id = ?",
                       (artifact_id,)).fetchone()
    return dict(row) if row else None


def verified_leaderboard(conn, track="A"):
    """Verified-only ranking: best final_eval per run, else best
    official_round; quick never appears (worker never marks quick verified)."""
    entries = []
    for run in conn.execute("SELECT * FROM runs WHERE track = ?",
                            (track.upper(),)):
        rows = results_for_run(conn, run["run_id"], verified_only=True)
        finals = [r for r in rows if r["mode"] == "final_eval"
                  and r["score"] is not None]
        officials = [r for r in rows if r["mode"] in ("official_round", "official")
                     and r["score"] is not None]
        best = (max(finals, key=lambda r: r["score"]) if finals
                else max(officials, key=lambda r: r["score"]) if officials
                else None)
        if best:
            entries.append({
                "run_id": run["run_id"],
                "score": best["score"],
                "mode": best["mode"],
                "verified": True,
                "result_id": best["id"],
            })
    entries.sort(key=lambda e: -e["score"])
    return {"schema": "ceb.hosted.leaderboard/v1", "track": track.upper(),
            "verified_only": True, "entries": entries}


def dumps(obj):
    return json.dumps(obj, indent=2) + "\n"
