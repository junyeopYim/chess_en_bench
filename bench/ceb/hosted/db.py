"""SQLite backend for the hosted pipeline.

Tables: runs, submissions, track_b_submissions, jobs, results, artifacts.
Results carry `verified` — true only when produced by the official worker
(ceb.hosted.worker) under a verifiable profile with every gate passed.

Concurrency: the connection runs in autocommit mode with a busy timeout, and
`claim_next_job` uses BEGIN IMMEDIATE so multiple workers can drain the queue
without ever processing the same job twice (P0.5).

Schema evolves additively: `migrate()` adds new columns/tables to an existing
database without deleting data, so old hosted DBs keep working.
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
CREATE TABLE IF NOT EXISTS track_b_submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    candidate_snapshot TEXT NOT NULL,
    baseline_snapshot TEXT NOT NULL,
    candidate_hash TEXT NOT NULL,
    baseline_hash TEXT NOT NULL,
    build_script TEXT NOT NULL,
    engine_relpath TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    detail TEXT,
    public_detail TEXT,
    worker_id TEXT,
    started_at TEXT,
    finished_at TEXT,
    lease_expires_at INTEGER,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    job_id INTEGER REFERENCES jobs(id),
    verified INTEGER NOT NULL DEFAULT 0,
    mode TEXT,
    profile TEXT,
    verification_grade TEXT,
    track TEXT NOT NULL DEFAULT 'A',
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

# Columns added after the original v1 schema; migrate() backfills them onto
# existing databases (idempotent — guarded by PRAGMA table_info).
_ADDED_COLUMNS = {
    "jobs": [
        ("public_detail", "TEXT"),
        ("worker_id", "TEXT"),
        ("started_at", "TEXT"),
        ("lease_expires_at", "INTEGER"),
        ("attempt_count", "INTEGER NOT NULL DEFAULT 0"),
    ],
    "results": [
        ("profile", "TEXT"),
        ("verification_grade", "TEXT"),
        ("track", "TEXT NOT NULL DEFAULT 'A'"),
    ],
}


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _epoch():
    return int(time.time())


def connect(db_path):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None -> autocommit; explicit BEGIN IMMEDIATE in
    # claim_next_job gives us a real write-locked transaction for atomic claims.
    conn = sqlite3.connect(str(db_path), isolation_level=None, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:  # pragma: no cover - some filesystems lack WAL
        pass
    migrate(conn)
    return conn


def migrate(conn):
    """Create missing tables and add missing columns without losing data."""
    conn.executescript(SCHEMA)
    for table, columns in _ADDED_COLUMNS.items():
        existing = {row["name"] for row in
                    conn.execute("PRAGMA table_info(%s)" % table)}
        for name, decl in columns:
            if name not in existing:
                try:
                    conn.execute("ALTER TABLE %s ADD COLUMN %s %s"
                                 % (table, name, decl))
                except sqlite3.OperationalError:  # pragma: no cover - lost race
                    pass


def init_db(db_path):
    conn = connect(db_path)
    conn.close()
    return Path(db_path)


def store_dir(db_path):
    """Object-store directory next to the database file."""
    db_path = Path(db_path)
    store = db_path.parent / (db_path.stem + "_store")
    store.mkdir(parents=True, exist_ok=True)
    return store


# ----- runs / submissions -----------------------------------------------------

def create_run(conn, run_id, track):
    conn.execute(
        "INSERT INTO runs (run_id, track, status, created_at) VALUES (?,?,?,?)",
        (run_id, track.upper(), "created", _now()))


def get_run(conn, run_id):
    row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def add_submission(conn, run_id, snapshot_path, tree_hash):
    cur = conn.execute(
        "INSERT INTO submissions (run_id, snapshot_path, tree_hash, created_at) "
        "VALUES (?,?,?,?)", (run_id, str(snapshot_path), tree_hash, _now()))
    return cur.lastrowid


def latest_submission(conn, run_id):
    row = conn.execute(
        "SELECT * FROM submissions WHERE run_id = ? ORDER BY id DESC LIMIT 1",
        (run_id,)).fetchone()
    return dict(row) if row else None


def add_track_b_submission(conn, run_id, *, candidate_snapshot, baseline_snapshot,
                           candidate_hash, baseline_hash, build_script,
                           engine_relpath):
    cur = conn.execute(
        "INSERT INTO track_b_submissions (run_id, candidate_snapshot, "
        "baseline_snapshot, candidate_hash, baseline_hash, build_script, "
        "engine_relpath, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (run_id, str(candidate_snapshot), str(baseline_snapshot),
         candidate_hash, baseline_hash, build_script, engine_relpath, _now()))
    return cur.lastrowid


def latest_track_b_submission(conn, run_id):
    row = conn.execute(
        "SELECT * FROM track_b_submissions WHERE run_id = ? "
        "ORDER BY id DESC LIMIT 1", (run_id,)).fetchone()
    return dict(row) if row else None


# ----- jobs -------------------------------------------------------------------

def enqueue_job(conn, run_id, kind):
    cur = conn.execute(
        "INSERT INTO jobs (run_id, kind, status, created_at) VALUES (?,?,?,?)",
        (run_id, kind, "queued", _now()))
    return cur.lastrowid


def next_queued_job(conn):
    """Oldest queued job (non-atomic peek; workers must use claim_next_job)."""
    row = conn.execute(
        "SELECT * FROM jobs WHERE status = 'queued' ORDER BY id LIMIT 1").fetchone()
    return dict(row) if row else None


def claim_next_job(conn, worker_id=None, lease_seconds=None):
    """Atomically claim the oldest claimable job. Returns the job dict (now in
    state 'running') or None when nothing is claimable.

    Claimable = queued, OR running with an expired lease (stale-worker
    recovery, when lease_seconds was set on the original claim). BEGIN
    IMMEDIATE takes the write lock up front, so if two workers race only one
    transitions the job queued->running; the other sees no claimable row.
    """
    now_str = _now()
    now_e = _epoch()
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT * FROM jobs WHERE status = 'queued' "
            "   OR (status = 'running' AND lease_expires_at IS NOT NULL "
            "       AND lease_expires_at < ?) "
            "ORDER BY id LIMIT 1", (now_e,)).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return None
        lease_expires = now_e + int(lease_seconds) if lease_seconds else None
        conn.execute(
            "UPDATE jobs SET status = 'running', worker_id = ?, started_at = ?, "
            "lease_expires_at = ?, attempt_count = COALESCE(attempt_count, 0) + 1 "
            "WHERE id = ? AND (status = 'queued' OR status = 'running')",
            (worker_id, now_str, lease_expires, row["id"]))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    job = dict(row)
    job.update(status="running", worker_id=worker_id, started_at=now_str,
               lease_expires_at=lease_expires,
               attempt_count=(row["attempt_count"] or 0) + 1)
    return job


def get_job(conn, job_id):
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def finish_job(conn, job_id, status, detail=None, public_detail=None):
    """Mark a job done/failed. detail is the operator-private reason;
    public_detail is the sanitized, agent-safe reason (P0.5)."""
    conn.execute(
        "UPDATE jobs SET status = ?, detail = ?, public_detail = ?, "
        "finished_at = ?, lease_expires_at = NULL WHERE id = ?",
        (status, detail, public_detail, _now(), job_id))


def _still_owns(row, job):
    """True if `job`'s claimer still owns the live jobs row (status, worker,
    attempt all unchanged). A stale worker whose lease was reclaimed fails this
    check — its attempt_count and worker_id no longer match."""
    return (row is not None and row["status"] == "running"
            and row["worker_id"] == job.get("worker_id")
            and row["attempt_count"] == job.get("attempt_count"))


def finish_job_if_owned(conn, job, status, detail=None, public_detail=None):
    """Mark a job done/failed ONLY if the caller still owns the claim (P0.5
    fencing). Returns True if it did. A reclaimed stale worker gets False and
    must not clobber the new owner's job."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT status, worker_id, attempt_count FROM jobs WHERE id = ?",
            (job["id"],)).fetchone()
        if not _still_owns(row, job):
            conn.execute("COMMIT")
            return False
        conn.execute(
            "UPDATE jobs SET status = ?, detail = ?, public_detail = ?, "
            "finished_at = ?, lease_expires_at = NULL WHERE id = ?",
            (status, detail, public_detail, _now(), job["id"]))
        conn.execute("COMMIT")
        return True
    except Exception:
        conn.execute("ROLLBACK")
        raise


def record_result_if_owned(conn, job, *, verified, mode, score, result_path,
                           profile=None, verification_grade=None, track="A"):
    """Atomically insert a result AND mark the job done — but only if the
    caller still owns the claim (P0.5 fencing). Returns the new result id, or
    None if ownership was lost (a stale worker reclaimed): in that case nothing
    is inserted, so no duplicate verified result can corrupt the leaderboard.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT status, worker_id, attempt_count FROM jobs WHERE id = ?",
            (job["id"],)).fetchone()
        if not _still_owns(row, job):
            conn.execute("COMMIT")
            return None
        cur = conn.execute(
            "INSERT INTO results (run_id, job_id, verified, mode, profile, "
            "verification_grade, track, score, result_path, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (job["run_id"], job["id"], 1 if verified else 0, mode, profile,
             verification_grade, track.upper(), score, str(result_path), _now()))
        conn.execute(
            "UPDATE jobs SET status = 'done', finished_at = ?, "
            "lease_expires_at = NULL WHERE id = ?", (_now(), job["id"]))
        conn.execute("COMMIT")
        return cur.lastrowid
    except Exception:
        conn.execute("ROLLBACK")
        raise


# ----- results ----------------------------------------------------------------

def add_result(conn, run_id, job_id, *, verified, mode, score, result_path,
               profile=None, verification_grade=None, track="A"):
    cur = conn.execute(
        "INSERT INTO results (run_id, job_id, verified, mode, profile, "
        "verification_grade, track, score, result_path, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (run_id, job_id, 1 if verified else 0, mode, profile,
         verification_grade, track.upper(), score, str(result_path), _now()))
    return cur.lastrowid


def results_for_run(conn, run_id, verified_only=False):
    query = "SELECT * FROM results WHERE run_id = ?"
    if verified_only:
        query += " AND verified = 1"
    return [dict(r) for r in conn.execute(query + " ORDER BY id", (run_id,))]


def select_best_verified_result(conn, run_id):
    """The single best verified result for a run (P0.4).

    Policy (shared by the leaderboard, `result show`, and the official-result
    API so they never disagree): prefer the best final-tier result
    (final_production / final_eval / track_b_official) over the best
    official-tier result; diagnostic/smoke results are never verified and so
    are never selected. Returns the result row dict, or None.
    """
    from ceb.hosted.profiles import result_tier, TIER_FINAL, TIER_OFFICIAL

    rows = [r for r in results_for_run(conn, run_id, verified_only=True)
            if r["score"] is not None]
    if not rows:
        return None
    finals = [r for r in rows if result_tier(r["mode"]) == TIER_FINAL]
    officials = [r for r in rows if result_tier(r["mode"]) == TIER_OFFICIAL]
    pool = finals or officials
    if not pool:
        return None
    return max(pool, key=lambda r: r["score"])


# ----- artifacts --------------------------------------------------------------

def register_artifact(conn, artifact_id, run_id, path, visibility):
    conn.execute(
        "INSERT OR REPLACE INTO artifacts (artifact_id, run_id, path, visibility) "
        "VALUES (?,?,?,?)", (artifact_id, run_id, str(path), visibility))


def get_artifact(conn, artifact_id):
    row = conn.execute("SELECT * FROM artifacts WHERE artifact_id = ?",
                       (artifact_id,)).fetchone()
    return dict(row) if row else None


# ----- leaderboard ------------------------------------------------------------

def verified_leaderboard(conn, track="A"):
    """Verified-only ranking using the shared selection policy (P0.4).

    One entry per run: its single best verified result (final-tier preferred
    over official-tier). Smoke/diagnostic results are never verified and never
    appear. Works for Track A (final_score) and Track B (delta Elo).
    """
    from ceb.hosted.models import SCHEMA_LEADERBOARD

    entries = []
    for run in conn.execute("SELECT * FROM runs WHERE track = ?",
                            (track.upper(),)):
        best = select_best_verified_result(conn, run["run_id"])
        if best:
            entries.append({
                "run_id": run["run_id"],
                "score": best["score"],
                "mode": best["mode"],
                "profile": best["profile"],
                "verification_grade": best["verification_grade"],
                "verified": True,
                "result_id": best["id"],
            })
    entries.sort(key=lambda e: -e["score"])
    return {"schema": SCHEMA_LEADERBOARD, "track": track.upper(),
            "verified_only": True, "entries": entries}


def dumps(obj):
    return json.dumps(obj, indent=2) + "\n"
