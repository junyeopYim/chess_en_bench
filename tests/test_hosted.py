"""Tests for the hosted pipeline: profiles, the engine-jail verification guard,
atomic job claiming, shared result selection, and the hosted API.

A VERIFIED result requires the docker engine jail, which is opt-in (it needs a
daemon + image), so the non-docker tests here cover the guard behaviour and use
directly-inserted verified rows to test selection/leaderboard/API consistency.
A full verified end-to-end path is exercised by the opt-in docker tests
(CEB_DOCKER_TESTS=1)."""

import json
from pathlib import Path

import pytest

from ceb.hosted import db as hosted_db
from ceb.hosted.models import SCHEMA_OFFICIAL_RESULT
from ceb.hosted.official_eval import run_official_eval, OfficialEvalError
from ceb.hosted.submissions import snapshot_workspace, SubmissionError
from ceb.hosted.worker import run_once

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples" / "submissions" / "minimal_uci_engine_python"
TINY_PACK = REPO_ROOT / "examples" / "eval_packs" / "tiny_private"
TINY_CONFIG = {"opponents": ["BenchRandom"], "games_per_opponent": 2,
               "movetime_ms": 30, "max_plies": 30, "openings_limit": 1}


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


def _insert_verified(db_path, run_id, *, mode, score, profile, grade, track="A"):
    """Directly insert a verified result row plus a minimal result file."""
    conn = hosted_db.connect(db_path)
    try:
        if hosted_db.get_run(conn, run_id) is None:
            hosted_db.create_run(conn, run_id, track)
        out = hosted_db.store_dir(db_path) / run_id
        out.mkdir(parents=True, exist_ok=True)
        result_path = out / ("result_%s_%s.json" % (mode, score))
        result_path.write_text(json.dumps({
            "schema": SCHEMA_OFFICIAL_RESULT, "run_id": run_id, "track": track,
            "mode": mode, "profile": profile, "verification_grade": grade,
            "verified": True, "score": {"final_score": score},
            "metadata": {"benchmark_version": "test"},
            "signature": {"status": "unsigned"}}))
        rid = hosted_db.add_result(
            conn, run_id, None, verified=True, mode=mode, score=score,
            result_path=result_path, profile=profile, verification_grade=grade,
            track=track)
    finally:
        conn.close()
    return rid


# ----- P0.2: smoke is diagnostic, never verified ------------------------------

@pytest.fixture(scope="module")
def smoke_db(tmp_path_factory):
    """A hosted DB with one completed SMOKE job (verified=false) for toy_run.

    Exercises the real worker pipeline (claim -> scan -> gate -> match -> sign
    -> leak scan -> artifact registration) without docker."""
    base = tmp_path_factory.mktemp("hosted")
    db_path = hosted_db.init_db(base / "hosted.sqlite")
    _submit(db_path, "toy_run", EXAMPLE)
    status = run_once(db_path, eval_pack_dir=str(TINY_PACK),
                      quick_test_mode=True, worker_id="w-smoke")
    assert status["status"] == "done", status
    return db_path


def test_smoke_job_is_done_but_unverified(smoke_db):
    conn = hosted_db.connect(smoke_db)
    try:
        results = hosted_db.results_for_run(conn, "toy_run")
    finally:
        conn.close()
    assert len(results) == 1
    row = results[0]
    assert bool(row["verified"]) is False           # smoke is never verified
    assert row["profile"] == "smoke"
    assert row["verification_grade"] == "diagnostic-smoke"
    result = json.loads(Path(row["result_path"]).read_text())
    assert result["schema"] == SCHEMA_OFFICIAL_RESULT
    assert result["verified"] is False
    assert result["profile"] == "smoke"
    assert result["verification_grade"] == "diagnostic-smoke"
    assert result["metadata"]["eval_pack_hash"].startswith("sha256:")


def test_smoke_never_on_hosted_leaderboard(smoke_db):
    conn = hosted_db.connect(smoke_db)
    try:
        board = hosted_db.verified_leaderboard(conn, track="A")
    finally:
        conn.close()
    assert board["verified_only"] is True
    assert board["entries"] == []  # the smoke result is excluded


def test_result_bundle_export_is_public_only(smoke_db, tmp_path):
    import zipfile
    from ceb.hosted.result_bundle import export_result_bundle

    conn = hosted_db.connect(smoke_db)
    try:
        out, manifest = export_result_bundle(
            conn, "toy_run", tmp_path / "bundle.zip", db_path=smoke_db)
    finally:
        conn.close()
    assert out.is_file()
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert any(n.endswith("official_result.json") for n in names)
    assert any(n.endswith("feedback.json") for n in names)
    assert "VERIFY.txt" in names and "bundle_manifest.json" in names
    # No private artifacts may be bundled.
    assert not any("scan_report.json" in n for n in names)
    assert not any("leak_scan.json" in n for n in names)
    assert not any(n.endswith("match_vs_BenchRandom.json") for n in names)


def test_smoke_records_worker_and_job_lifecycle(smoke_db):
    conn = hosted_db.connect(smoke_db)
    try:
        jobs = conn.execute("SELECT * FROM jobs WHERE run_id = 'toy_run'").fetchall()
    finally:
        conn.close()
    assert len(jobs) == 1
    job = dict(jobs[0])
    assert job["status"] == "done"
    assert job["worker_id"] == "w-smoke"
    assert job["started_at"] and job["finished_at"]
    assert job["attempt_count"] == 1


# ----- P0.1: verified results require the docker engine jail -------------------

def test_official_profile_refuses_without_jail(tmp_path):
    # A verifiable profile without --engine-jail docker fails BEFORE evaluating.
    db_path = hosted_db.init_db(tmp_path / "hosted.sqlite")
    _submit(db_path, "needs_jail", EXAMPLE)
    status = run_once(db_path, eval_pack_dir=str(TINY_PACK), profile="official",
                      engine_jail="none")
    assert status["status"] == "failed"
    assert "docker" in status["detail"]
    conn = hosted_db.connect(db_path)
    try:
        assert hosted_db.results_for_run(conn, "needs_jail",
                                         verified_only=True) == []
    finally:
        conn.close()


def test_missing_jail_image_is_actionable(tmp_path, monkeypatch):
    # P0.1: a verifiable profile with the docker jail required but the image
    # missing fails fast with an actionable, build-it-first message.
    import ceb.jail.docker_engine as de

    def _raise(image=de.JAIL_IMAGE):
        raise de.DockerJailError(
            "engine jail image %r not found. Build it first:\n"
            "  bash scripts/build_jail_image.sh" % de.JAIL_IMAGE)

    monkeypatch.setattr(de, "ensure_ready", _raise)
    with pytest.raises(OfficialEvalError, match="build_jail_image"):
        run_official_eval(
            run_id="x", snapshot=EXAMPLE, eval_pack_dir=str(TINY_PACK),
            out_dir=tmp_path / "out", profile="official", engine_jail="docker")


def test_dev_unjailed_runs_but_is_not_verified(tmp_path):
    # The dev escape hatch downgrades a verifiable profile to a diagnostic
    # (unverified) result; it must never reach the leaderboard.
    out_dir = tmp_path / "out"
    result = run_official_eval(
        run_id="dev_run", snapshot=EXAMPLE, eval_pack_dir=str(TINY_PACK),
        out_dir=out_dir, profile="official", engine_jail="none",
        allow_unjailed=True, mode_config=TINY_CONFIG)
    assert result["verified"] is False
    assert result["verification_grade"] == "diagnostic-unjailed"
    assert result["profile"] == "official"


def test_official_eval_refuses_when_public_artifact_would_leak(tmp_path,
                                                               monkeypatch):
    # P0.8: if a hidden pack secret would reach a public artifact, the official
    # evaluation refuses to verify and writes a private leak report.
    import ceb.rounds.round_runner as rr

    leak_fen = "8/8/8/3k4/8/8/4Q3/4K3"  # a hidden FEN from the tiny pack

    def _leaky_feedback(round_report):
        return {"schema": "ceb.round.feedback/v1", "leaked_position": leak_fen}

    monkeypatch.setattr(rr, "make_feedback", _leaky_feedback)
    out_dir = tmp_path / "out"
    with pytest.raises(OfficialEvalError, match="leak"):
        run_official_eval(
            run_id="leak_run", snapshot=EXAMPLE, eval_pack_dir=str(TINY_PACK),
            out_dir=out_dir, quick_test_mode=True)
    leak_report = json.loads(
        (out_dir / "leak_scan.json").read_text())
    assert leak_report["passed"] is False
    assert leak_report["leaks"]


def test_leak_scan_catches_nested_public_report(tmp_path, monkeypatch):
    # Regression: a hidden secret reaching the NESTED round_<N>/report.public.json
    # (a served public artifact) must be caught — the leak scan is recursive.
    import ceb.rounds.round_runner as rr

    leak_fen = "8/8/8/3k4/8/8/4Q3/4K3"
    orig = rr.make_public_report

    def _leaky_public(round_report, pack):
        report = orig(round_report, pack)
        report["leaked_position"] = leak_fen
        return report

    monkeypatch.setattr(rr, "make_public_report", _leaky_public)
    out_dir = tmp_path / "out"
    with pytest.raises(OfficialEvalError, match="leak"):
        run_official_eval(
            run_id="leak_nested", snapshot=EXAMPLE, eval_pack_dir=str(TINY_PACK),
            out_dir=out_dir, quick_test_mode=True)
    leak_report = json.loads((out_dir / "leak_scan.json").read_text())
    assert leak_report["passed"] is False
    # The leak was found in the nested round directory, not the job root.
    assert any("round_1/report.public.json" in lk["artifact"]
               for lk in leak_report["leaks"])


def test_worker_refuses_without_eval_pack(tmp_path):
    db_path = hosted_db.init_db(tmp_path / "hosted.sqlite")
    _submit(db_path, "no_pack", EXAMPLE)
    status = run_once(db_path, eval_pack_dir=None, quick_test_mode=True)
    assert status["status"] == "failed"
    assert "eval pack" in status["detail"]


def test_worker_refuses_when_scan_fails(tmp_path):
    cheater = tmp_path / "cheater"
    cheater.mkdir()
    (cheater / "engine.py").write_text("import chess\n")
    wrapper = cheater / "engine"
    wrapper.write_text("#!/usr/bin/env bash\nexec python3 engine.py\n")
    wrapper.chmod(0o755)
    db_path = hosted_db.init_db(tmp_path / "hosted.sqlite")
    _submit(db_path, "cheater", cheater)
    status = run_once(db_path, eval_pack_dir=str(TINY_PACK), quick_test_mode=True)
    assert status["status"] == "failed"
    assert "scan" in status["detail"]


def test_worker_refuses_when_strict_gate_fails(tmp_path):
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
    status = run_once(db_path, eval_pack_dir=str(TINY_PACK), quick_test_mode=True)
    assert status["status"] == "failed"
    conn = hosted_db.connect(db_path)
    try:
        assert hosted_db.results_for_run(conn, "gate_fail",
                                         verified_only=True) == []
        job = conn.execute("SELECT * FROM jobs WHERE run_id = 'gate_fail'").fetchone()
    finally:
        conn.close()
    # Failed jobs carry both a sanitized public detail and a private detail.
    assert job["status"] == "failed"
    assert job["public_detail"] and job["detail"]


def test_snapshot_rejects_symlinks(tmp_path):
    import os
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "engine").write_text("#!/bin/bash\n")
    os.symlink("/etc/passwd", workspace / "link")
    with pytest.raises(SubmissionError, match="symlink"):
        snapshot_workspace(workspace, tmp_path / "snap")


# ----- P0.4: one shared best-verified selection -------------------------------

def test_select_best_prefers_final_over_later_higher_official(tmp_path):
    db_path = hosted_db.init_db(tmp_path / "hosted.sqlite")
    _insert_verified(db_path, "sel_run", mode="official_round", score=900.0,
                     profile="official", grade="verified-official")
    _insert_verified(db_path, "sel_run", mode="final_eval", score=700.0,
                     profile="final-eval", grade="verified-final-eval")
    _insert_verified(db_path, "sel_run", mode="official_round", score=950.0,
                     profile="official", grade="verified-official")  # later, higher
    conn = hosted_db.connect(db_path)
    try:
        best = hosted_db.select_best_verified_result(conn, "sel_run")
        board = hosted_db.verified_leaderboard(conn, track="A")
    finally:
        conn.close()
    # Final-tier wins even though a later official row scored higher.
    assert best["mode"] == "final_eval"
    assert best["score"] == 700.0
    entry = next(e for e in board["entries"] if e["run_id"] == "sel_run")
    assert entry["score"] == 700.0 and entry["mode"] == "final_eval"


def test_select_best_falls_back_to_official(tmp_path):
    db_path = hosted_db.init_db(tmp_path / "hosted.sqlite")
    _insert_verified(db_path, "off_run", mode="official_round", score=820.0,
                     profile="official", grade="verified-official")
    _insert_verified(db_path, "off_run", mode="official_round", score=880.0,
                     profile="official", grade="verified-official")
    conn = hosted_db.connect(db_path)
    try:
        best = hosted_db.select_best_verified_result(conn, "off_run")
    finally:
        conn.close()
    assert best["mode"] == "official_round" and best["score"] == 880.0


# ----- P0.5: atomic job claiming ----------------------------------------------

def test_two_workers_cannot_claim_the_same_job(tmp_path):
    db_path = hosted_db.init_db(tmp_path / "hosted.sqlite")
    conn0 = hosted_db.connect(db_path)
    try:
        hosted_db.create_run(conn0, "r", "A")
        hosted_db.enqueue_job(conn0, "r", "official_eval")
    finally:
        conn0.close()
    a = hosted_db.connect(db_path)
    b = hosted_db.connect(db_path)
    try:
        claim_a = hosted_db.claim_next_job(a, worker_id="A")
        claim_b = hosted_db.claim_next_job(b, worker_id="B")
    finally:
        a.close()
        b.close()
    claimed = [c for c in (claim_a, claim_b) if c is not None]
    assert len(claimed) == 1            # exactly one worker won
    assert claimed[0]["status"] == "running"


def test_running_job_not_reclaimed_without_lease(tmp_path):
    db_path = hosted_db.init_db(tmp_path / "hosted.sqlite")
    conn = hosted_db.connect(db_path)
    try:
        hosted_db.create_run(conn, "r", "A")
        hosted_db.enqueue_job(conn, "r", "official_eval")
        first = hosted_db.claim_next_job(conn, worker_id="A")  # no lease
        second = hosted_db.claim_next_job(conn, worker_id="B")
    finally:
        conn.close()
    assert first is not None and second is None


def test_stale_running_job_is_reclaimed(tmp_path):
    db_path = hosted_db.init_db(tmp_path / "hosted.sqlite")
    conn = hosted_db.connect(db_path)
    try:
        hosted_db.create_run(conn, "r", "A")
        job_id = hosted_db.enqueue_job(conn, "r", "official_eval")
        hosted_db.claim_next_job(conn, worker_id="A", lease_seconds=1000)
        # Simulate a dead worker: force the lease into the past.
        conn.execute("UPDATE jobs SET lease_expires_at = 1 WHERE id = ?", (job_id,))
        reclaimed = hosted_db.claim_next_job(conn, worker_id="B")
    finally:
        conn.close()
    assert reclaimed is not None
    assert reclaimed["worker_id"] == "B"
    assert reclaimed["attempt_count"] == 2


def test_reclaimed_stale_worker_cannot_record_duplicate(tmp_path):
    # P0.5 fencing: after worker B reclaims a stale job, the original worker A
    # must NOT be able to record its result — exactly one verified result.
    db_path = hosted_db.init_db(tmp_path / "hosted.sqlite")
    conn = hosted_db.connect(db_path)
    try:
        hosted_db.create_run(conn, "r", "A")
        job_id = hosted_db.enqueue_job(conn, "r", "official_eval")
        job_a = hosted_db.claim_next_job(conn, worker_id="A", lease_seconds=1000)
        conn.execute("UPDATE jobs SET lease_expires_at = 1 WHERE id = ?", (job_id,))
        job_b = hosted_db.claim_next_job(conn, worker_id="B")

        common = dict(verified=True, mode="official_round", score=900.0,
                      result_path="/tmp/x.json", profile="official",
                      verification_grade="verified-official", track="A")
        # Stale worker A: ownership lost -> no insert.
        assert hosted_db.record_result_if_owned(conn, job_a, **common) is None
        # New owner B: records.
        assert hosted_db.record_result_if_owned(conn, job_b, **common) is not None
        # A late failure attempt by A must also be fenced out.
        assert hosted_db.finish_job_if_owned(conn, job_a, "failed") is False
        results = hosted_db.results_for_run(conn, "r", verified_only=True)
        job = hosted_db.get_job(conn, job_id)
    finally:
        conn.close()
    assert len(results) == 1                 # no duplicate
    assert job["status"] == "done"           # B's completion stands


# ----- P0.6: Track B hosted (guard, non-docker) -------------------------------

def test_track_b_hosted_refuses_verified_without_jail(tmp_path):
    from ceb.hosted.track_b_eval import run_hosted_track_b
    from ceb.track_b.official_pipeline import TrackBPipelineError

    cand = tmp_path / "cand"
    base = tmp_path / "base"
    for tree, val in ((base, 1), (cand, 2)):
        tree.mkdir(parents=True)
        (tree / "src").mkdir()
        (tree / "src" / "search.cpp").write_text("int m = %d;\n" % val)
    with pytest.raises(TrackBPipelineError, match="docker"):
        run_hosted_track_b(
            run_id="tb", candidate_src=cand, baseline_src=base,
            build_script="ceb_build.sh", engine_relpath="ceb_engine",
            eval_pack_dir=None, out_dir=tmp_path / "out", engine_jail="none",
            profile="official", root=REPO_ROOT)


# ----- hosted API -------------------------------------------------------------

@pytest.fixture()
def api_client(tmp_path_factory, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    base = tmp_path_factory.mktemp("api")
    db_path = hosted_db.init_db(base / "hosted.sqlite")
    # A smoke run (registers public + private artifacts) ...
    _submit(db_path, "toy_run", EXAMPLE)
    assert run_once(db_path, eval_pack_dir=str(TINY_PACK),
                    quick_test_mode=True)["status"] == "done"
    # ... and directly-inserted verified results for leaderboard/official-result.
    _insert_verified(db_path, "win_run", mode="official_round", score=900.0,
                     profile="official", grade="verified-official")
    _insert_verified(db_path, "win_run", mode="final_eval", score=700.0,
                     profile="final-eval", grade="verified-final-eval")
    monkeypatch.setenv("CEB_HOSTED_DB", str(db_path))
    from fastapi.testclient import TestClient
    from ceb.api.main import app
    client = TestClient(app)
    client._db_path = db_path
    return client


def test_api_health_still_works(api_client):
    response = api_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_api_hosted_leaderboard_verified_only(api_client):
    board = api_client.get("/api/hosted/leaderboard?track=A").json()
    assert board["verified_only"] is True
    runs = [e["run_id"] for e in board["entries"]]
    assert "win_run" in runs        # verified
    assert "toy_run" not in runs    # smoke is excluded


def test_api_official_result_matches_leaderboard(api_client):
    # The official-result endpoint and the leaderboard use the same selector.
    board = api_client.get("/api/hosted/leaderboard?track=A").json()
    entry = next(e for e in board["entries"] if e["run_id"] == "win_run")
    result = api_client.get("/api/hosted/runs/win_run/official-result").json()
    assert result["verified"] is True
    assert result["mode"] == entry["mode"] == "final_eval"
    assert result["score"]["final_score"] == entry["score"] == 700.0


def test_api_private_artifact_not_served(api_client):
    conn = hosted_db.connect(api_client._db_path)
    try:
        rows = conn.execute("SELECT * FROM artifacts").fetchall()
    finally:
        conn.close()
    private = [r for r in rows if r["visibility"] != "public"]
    public = [r for r in rows if r["visibility"] == "public"]
    assert private and public
    assert api_client.get("/api/hosted/artifacts/%s"
                          % private[0]["artifact_id"]).status_code == 404
    assert api_client.get("/api/hosted/artifacts/%s"
                          % public[0]["artifact_id"]).status_code == 200


def test_api_path_traversal_rejected(api_client):
    assert api_client.get("/api/hosted/artifacts/..%2F..%2Fetc%2Fpasswd"
                          ).status_code in (400, 404)
    assert api_client.get("/api/hosted/artifacts/.hidden").status_code in (400, 404)


def test_api_missing_result_404(api_client):
    assert api_client.get("/api/hosted/runs/nope").status_code == 404
    assert api_client.get("/api/hosted/runs/nope/official-result").status_code == 404
    # toy_run has only an unverified smoke result -> no official result.
    assert api_client.get("/api/hosted/runs/toy_run/official-result"
                          ).status_code == 404


def test_api_admin_endpoints_gated(api_client, monkeypatch):
    payload = {"run_id": "api_run", "track": "A"}
    monkeypatch.delenv("CEB_ADMIN_TOKEN", raising=False)
    assert api_client.post("/api/hosted/runs", json=payload).status_code == 503
    monkeypatch.setenv("CEB_ADMIN_TOKEN", "sekrit")
    assert api_client.post("/api/hosted/runs", json=payload).status_code == 403
    response = api_client.post("/api/hosted/runs", json=payload,
                               headers={"X-CEB-Admin-Token": "sekrit"})
    assert response.status_code == 200
