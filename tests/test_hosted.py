"""Tests for the hosted pipeline (P0.4) and hosted API (P0.8)."""

import json
import shutil
from pathlib import Path

import pytest

from ceb.hosted import db as hosted_db
from ceb.hosted.submissions import snapshot_workspace, SubmissionError
from ceb.hosted.worker import run_once

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples" / "submissions" / "minimal_uci_engine_python"
TINY_PACK = REPO_ROOT / "examples" / "eval_packs" / "tiny_private"


def _submit(db_path, run_id, workspace):
    conn = hosted_db.connect(db_path)
    try:
        if hosted_db.get_run(conn, run_id) is None:
            hosted_db.create_run(conn, run_id, "A")
        dest = hosted_db.store_dir(db_path) / run_id / "snapshots" / "s1"
        snapshot, tree_hash = snapshot_workspace(workspace, dest)
        hosted_db.add_submission(conn, run_id, snapshot, tree_hash)
        hosted_db.enqueue_job(conn, run_id, "official_eval")
    finally:
        conn.close()
    return snapshot


@pytest.fixture(scope="module")
def verified_db(tmp_path_factory):
    """A hosted DB with one verified result from the toy worker flow."""
    base = tmp_path_factory.mktemp("hosted")
    db_path = hosted_db.init_db(base / "hosted.sqlite")
    _submit(db_path, "toy_run", EXAMPLE)
    status = run_once(db_path, eval_pack_dir=str(TINY_PACK),
                      quick_test_mode=True)
    assert status["status"] == "done", status
    return db_path


def test_worker_produces_verified_result(verified_db):
    conn = hosted_db.connect(verified_db)
    try:
        results = hosted_db.results_for_run(conn, "toy_run")
    finally:
        conn.close()
    assert len(results) == 1
    row = results[0]
    assert bool(row["verified"]) is True
    assert row["mode"] == "official_round"
    result = json.loads(Path(row["result_path"]).read_text())
    assert result["schema"] == "ceb.hosted.official_result/v1"
    assert result["verified"] is True
    assert result["config_profile"] == "quick-test"
    assert result["metadata"]["eval_pack_hash"].startswith("sha256:")
    assert result["signature"]["status"] in ("signed", "unsigned")


def test_hosted_leaderboard_is_verified_only(verified_db):
    conn = hosted_db.connect(verified_db)
    try:
        board = hosted_db.verified_leaderboard(conn, track="A")
    finally:
        conn.close()
    assert board["verified_only"] is True
    assert [e["run_id"] for e in board["entries"]] == ["toy_run"]
    assert all(e["verified"] for e in board["entries"])


def test_self_reported_rounds_never_appear_verified(tmp_path):
    # A local (self-reported) leaderboard never claims verification, and an
    # empty hosted DB has no verified entries regardless of local runs.
    from ceb.scoring.track_a import compute_leaderboard

    board = compute_leaderboard(tmp_path)
    assert board["verified_only"] is False
    db_path = hosted_db.init_db(tmp_path / "hosted.sqlite")
    conn = hosted_db.connect(db_path)
    try:
        hosted = hosted_db.verified_leaderboard(conn)
    finally:
        conn.close()
    assert hosted["entries"] == []


def test_worker_refuses_without_eval_pack(tmp_path):
    db_path = hosted_db.init_db(tmp_path / "hosted.sqlite")
    _submit(db_path, "no_pack", EXAMPLE)
    status = run_once(db_path, eval_pack_dir=None, quick_test_mode=True)
    assert status["status"] == "failed"
    assert "eval pack" in status["detail"]
    conn = hosted_db.connect(db_path)
    try:
        assert hosted_db.results_for_run(conn, "no_pack",
                                         verified_only=True) == []
    finally:
        conn.close()


def test_worker_refuses_when_scan_fails(tmp_path):
    cheater = tmp_path / "cheater"
    cheater.mkdir()
    (cheater / "engine.py").write_text("import chess\n")
    wrapper = cheater / "engine"
    wrapper.write_text("#!/usr/bin/env bash\nexec python3 engine.py\n")
    wrapper.chmod(0o755)
    db_path = hosted_db.init_db(tmp_path / "hosted.sqlite")
    _submit(db_path, "cheater", cheater)
    status = run_once(db_path, eval_pack_dir=str(TINY_PACK),
                      quick_test_mode=True)
    assert status["status"] == "failed"
    assert "scan" in status["detail"]


def test_worker_refuses_when_strict_gate_fails(tmp_path):
    # Fully legal engine, but without 'go perft': strict gate must fail and
    # nothing verified may be recorded.
    workspace = tmp_path / "no_perft"
    workspace.mkdir()
    source = (EXAMPLE / "engine.py").read_text()
    patched = source.replace('if len(tokens) >= 3 and tokens[1] == "perft":',
                             "if False:")
    (workspace / "engine.py").write_text(patched)
    wrapper = workspace / "engine"
    wrapper.write_text('#!/usr/bin/env bash\nexec python3 "$(dirname "$0")/engine.py"\n')
    wrapper.chmod(0o755)

    db_path = hosted_db.init_db(tmp_path / "hosted.sqlite")
    _submit(db_path, "gate_fail", workspace)
    status = run_once(db_path, eval_pack_dir=str(TINY_PACK),
                      quick_test_mode=True)
    assert status["status"] == "failed"
    conn = hosted_db.connect(db_path)
    try:
        assert hosted_db.results_for_run(conn, "gate_fail",
                                         verified_only=True) == []
    finally:
        conn.close()


def test_snapshot_rejects_symlinks(tmp_path):
    import os
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "engine").write_text("#!/bin/bash\n")
    os.symlink("/etc/passwd", workspace / "link")
    with pytest.raises(SubmissionError, match="symlink"):
        snapshot_workspace(workspace, tmp_path / "snap")


# ----- hosted API ----------------------------------------------------------------

@pytest.fixture()
def api_client(verified_db, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    monkeypatch.setenv("CEB_HOSTED_DB", str(verified_db))
    from fastapi.testclient import TestClient
    from ceb.api.main import app
    return TestClient(app)


def test_api_health_still_works(api_client):
    response = api_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_api_hosted_leaderboard_verified_only(api_client):
    response = api_client.get("/api/hosted/leaderboard?track=A")
    assert response.status_code == 200
    board = response.json()
    assert board["verified_only"] is True
    assert board["entries"][0]["run_id"] == "toy_run"


def test_api_private_artifact_not_served(api_client, verified_db):
    conn = hosted_db.connect(verified_db)
    try:
        rows = conn.execute("SELECT * FROM artifacts").fetchall()
    finally:
        conn.close()
    private = [r for r in rows if r["visibility"] != "public"]
    public = [r for r in rows if r["visibility"] == "public"]
    assert private and public  # the worker registered both kinds
    response = api_client.get("/api/hosted/artifacts/%s"
                              % private[0]["artifact_id"])
    assert response.status_code == 404  # deny: private looks like missing
    response = api_client.get("/api/hosted/artifacts/%s"
                              % public[0]["artifact_id"])
    assert response.status_code == 200


def test_api_path_traversal_rejected(api_client):
    assert api_client.get("/api/hosted/artifacts/..%2F..%2Fetc%2Fpasswd"
                          ).status_code in (400, 404)
    assert api_client.get("/api/hosted/artifacts/.hidden").status_code in (400, 404)


def test_api_missing_result_404(api_client):
    assert api_client.get("/api/hosted/runs/nope").status_code == 404
    assert api_client.get("/api/hosted/runs/nope/official-result").status_code == 404


def test_api_admin_endpoints_gated(api_client, monkeypatch):
    payload = {"run_id": "api_run", "track": "A"}
    # No token configured: disabled.
    monkeypatch.delenv("CEB_ADMIN_TOKEN", raising=False)
    assert api_client.post("/api/hosted/runs", json=payload).status_code == 503
    # Token configured but wrong/missing: forbidden.
    monkeypatch.setenv("CEB_ADMIN_TOKEN", "sekrit")
    assert api_client.post("/api/hosted/runs", json=payload).status_code == 403
    # Correct token: works.
    response = api_client.post("/api/hosted/runs", json=payload,
                               headers={"X-CEB-Admin-Token": "sekrit"})
    assert response.status_code == 200


def test_api_official_result_endpoint(api_client):
    response = api_client.get("/api/hosted/runs/toy_run/official-result")
    assert response.status_code == 200
    result = response.json()
    assert result["verified"] is True
    assert "metadata" in result
