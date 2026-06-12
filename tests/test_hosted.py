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


def _register_result_with_artifacts(db_path, run_id, *, job_id, mode, score,
                                    verified, profile, grade, public_names,
                                    private_names=()):
    """Insert a result and register public/private artifacts under its job dir."""
    store = hosted_db.store_dir(db_path)
    job_dir = store / run_id / ("job_%d_attempt_1" % job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    result_path = job_dir / "official_result.json"
    conn = hosted_db.connect(db_path)
    try:
        if hosted_db.get_run(conn, run_id) is None:
            hosted_db.create_run(conn, run_id, "A")
        for name in public_names + tuple(private_names):
            (job_dir / name).write_text('{"x": 1}')
        rid = hosted_db.add_result(
            conn, run_id, job_id, verified=verified, mode=mode, score=score,
            result_path=result_path, profile=profile, verification_grade=grade,
            track="A")
        for name in public_names:
            hosted_db.register_artifact(conn, "%s_j%d_%s" % (run_id, job_id, name),
                                        run_id, job_dir / name, "public")
        for name in private_names:
            hosted_db.register_artifact(conn, "%s_j%d_%s" % (run_id, job_id, name),
                                        run_id, job_dir / name, "private")
    finally:
        conn.close()
    return rid


def test_result_bundle_selected_only(tmp_path):
    # F: a run with smoke + official + final-production exports ONLY the
    # final-production (selected) public artifacts, never private ones.
    import zipfile
    from ceb.hosted.result_bundle import export_result_bundle

    db_path = hosted_db.init_db(tmp_path / "hosted.sqlite")
    _register_result_with_artifacts(
        db_path, "run", job_id=1, mode="official_round", score=800.0,
        verified=False, profile="smoke", grade="diagnostic-smoke",
        public_names=("official_result.json", "feedback.json"))
    _register_result_with_artifacts(
        db_path, "run", job_id=2, mode="official_round", score=820.0,
        verified=True, profile="official", grade="verified-official",
        public_names=("official_result.json", "feedback.json"),
        private_names=("scan_report.json",))
    final_id = _register_result_with_artifacts(
        db_path, "run", job_id=3, mode="final_production", score=700.0,
        verified=True, profile="final-production", grade="verified-final-production",
        public_names=("official_result.json", "feedback.json"),
        private_names=("scan_report.json", "leak_scan.json"))

    conn = hosted_db.connect(db_path)
    try:
        out, manifest = export_result_bundle(
            conn, "run", tmp_path / "bundle.zip", db_path=db_path)
    finally:
        conn.close()
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert manifest["selected_result_id"] == final_id
    assert manifest["selected_mode"] == "final_production"
    assert manifest["official"] is True
    # Only the final-production (job_3) artifacts, never job_1/job_2.
    assert any("job_3_attempt_1/official_result.json" in n for n in names)
    assert not any("job_1_attempt_1" in n for n in names)
    assert not any("job_2_attempt_1" in n for n in names)
    # No private artifacts ever.
    assert not any("scan_report.json" in n for n in names)
    assert not any("leak_scan.json" in n for n in names)
    assert "VERIFY.txt" in names and "bundle_manifest.json" in names


def test_result_bundle_no_verified_requires_include_all(smoke_db, tmp_path):
    from ceb.hosted.result_bundle import export_result_bundle, ResultBundleError
    import zipfile

    conn = hosted_db.connect(smoke_db)
    try:
        # Default (official) export refuses when there is no verified result.
        with pytest.raises(ResultBundleError, match="no verified result"):
            export_result_bundle(conn, "toy_run", tmp_path / "b1.zip",
                                 db_path=smoke_db)
        # Diagnostic bundle works and is marked non-official.
        out, manifest = export_result_bundle(
            conn, "toy_run", tmp_path / "b2.zip", db_path=smoke_db,
            include_all_public=True)
    finally:
        conn.close()
    assert manifest["official"] is False and manifest["selected_only"] is False
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert any(n.endswith("official_result.json") for n in names)
    assert not any("scan_report.json" in n for n in names)


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


def test_official_eval_rejects_demo_pack(tmp_path, monkeypatch):
    # A: a verifiable profile refuses to verify against the committed demo pack.
    # Trust is checked before the engine runs, so we pass the jail pre-flight.
    import ceb.jail.docker_engine as de
    monkeypatch.setattr(de, "ensure_ready", lambda image=de.JAIL_IMAGE: None)
    with pytest.raises(OfficialEvalError, match="eval pack"):
        run_official_eval(
            run_id="x", snapshot=EXAMPLE, eval_pack_dir=str(TINY_PACK),
            out_dir=tmp_path / "o", profile="official", engine_jail="docker")


def test_official_eval_requires_pinned_pack(tmp_path, monkeypatch, official_pack):
    # 1: a verified result needs the eval pack hash PINNED; with a trusted but
    # unpinned pack it refuses (before evaluating).
    import ceb.jail.docker_engine as de
    monkeypatch.setattr(de, "ensure_ready", lambda image=de.JAIL_IMAGE: None)
    with pytest.raises(OfficialEvalError, match="PINNED"):
        run_official_eval(
            run_id="x", snapshot=EXAMPLE, eval_pack_dir=str(official_pack),
            out_dir=tmp_path / "o", profile="official", engine_jail="docker")


def test_official_eval_requires_ed25519_key(tmp_path, monkeypatch, official_pack):
    # B: a verified result needs an Ed25519 key; with a trusted+pinned pack but
    # no key it refuses (before evaluating).
    from ceb.hosted.eval_pack_trust import compute_eval_pack_hash
    import ceb.jail.docker_engine as de
    monkeypatch.setattr(de, "ensure_ready", lambda image=de.JAIL_IMAGE: None)
    monkeypatch.delenv("CEB_SIGNING_PRIVATE_KEY", raising=False)
    with pytest.raises(OfficialEvalError, match="Ed25519"):
        run_official_eval(
            run_id="x", snapshot=EXAMPLE, eval_pack_dir=str(official_pack),
            out_dir=tmp_path / "o", profile="official", engine_jail="docker",
            official_pack_hashes=[compute_eval_pack_hash(official_pack)])


def test_dev_allow_demo_pack_is_never_verified(tmp_path, monkeypatch):
    # A/regression: --dev-allow-demo-pack must downgrade to a diagnostic, never
    # verified (parallel to --dev-allow-unjailed / --dev-allow-unsigned).
    import shutil
    import ceb.jail.docker_engine as de
    import ceb.hosted.official_eval as oe
    from ceb.hosted.signing import generate_keypair
    from conftest import make_official_pack

    monkeypatch.setattr(de, "ensure_ready", lambda image=de.JAIL_IMAGE: None)
    generate_keypair(tmp_path / "priv.pem", tmp_path / "pub.pem")
    monkeypatch.setenv("CEB_SIGNING_PRIVATE_KEY", str(tmp_path / "priv.pem"))

    def _fake_round(snapshot, round_number, **kw):
        return ({"schema": "x", "mode": kw["mode"],
                 "score": {"final_score": 0.0}}, {"schema": "fb"}, None)

    monkeypatch.setattr(oe, "run_round", _fake_round)
    # A pack with a valid official manifest but under the repo's examples/.
    probe = REPO_ROOT / "examples" / "_demo_downgrade_probe"
    try:
        make_official_pack(probe)
        result = run_official_eval(
            run_id="x", snapshot=EXAMPLE, eval_pack_dir=str(probe),
            out_dir=tmp_path / "o", profile="official", engine_jail="docker",
            allow_demo_pack=True)
    finally:
        shutil.rmtree(probe, ignore_errors=True)
    assert result["verified"] is False
    assert result["verification_grade"] == "diagnostic-untrusted-pack"
    assert result["metadata"]["eval_pack_trusted"] is False


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


def test_api_track_b_submission(api_client, tmp_path, monkeypatch):
    # E: admin-only Track B submission snapshots both trees and enqueues a job.
    cand = tmp_path / "cand"
    base = tmp_path / "base"
    for tree in (cand, base):
        (tree / "src").mkdir(parents=True)
        (tree / "src" / "search.cpp").write_text("int x = 1;\n")
    payload = {"candidate_src": str(cand), "baseline_src": str(base)}
    # No admin token -> disabled.
    monkeypatch.delenv("CEB_ADMIN_TOKEN", raising=False)
    assert api_client.post("/api/hosted/runs/tbrun/track-b-submissions",
                           json=payload).status_code == 503
    monkeypatch.setenv("CEB_ADMIN_TOKEN", "sekrit")
    resp = api_client.post("/api/hosted/runs/tbrun/track-b-submissions",
                           json=payload, headers={"X-CEB-Admin-Token": "sekrit"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["kind"] == "track_b_official_eval"
    assert data["candidate_hash"].startswith("sha256:")
    assert data["job_id"]


def test_api_track_b_submission_rejects_symlink(api_client, tmp_path, monkeypatch):
    import os
    cand = tmp_path / "cand"
    base = tmp_path / "base"
    for tree in (cand, base):
        tree.mkdir()
        (tree / "src.cpp").write_text("int x;\n")
    os.symlink("/etc/passwd", cand / "link")
    monkeypatch.setenv("CEB_ADMIN_TOKEN", "sekrit")
    resp = api_client.post("/api/hosted/runs/tbsym/track-b-submissions",
                           json={"candidate_src": str(cand), "baseline_src": str(base)},
                           headers={"X-CEB-Admin-Token": "sekrit"})
    assert resp.status_code == 400
    assert "symlink" in resp.json()["detail"]


def test_api_upload_streaming_rejects_oversized(api_client, monkeypatch):
    # G: the streaming upload enforces a byte limit as it reads.
    monkeypatch.setenv("CEB_ADMIN_TOKEN", "sekrit")
    monkeypatch.setattr("ceb.api.main._MAX_UPLOAD_BYTES", 100)
    api_client.post("/api/hosted/runs", json={"run_id": "uprun", "track": "A"},
                    headers={"X-CEB-Admin-Token": "sekrit"})
    resp = api_client.post(
        "/api/hosted/runs/uprun/upload?filename=ws.tar.gz",
        content=b"x" * 5000, headers={"X-CEB-Admin-Token": "sekrit"})
    assert resp.status_code == 413


# ----- H: official readiness check --------------------------------------------

def test_readiness_check_not_ready_with_demo_pack(tmp_path):
    from ceb.hosted.readiness import readiness_check

    db_path = hosted_db.init_db(tmp_path / "hosted.sqlite")
    report = readiness_check(db_path=str(db_path), eval_pack_dir=str(TINY_PACK),
                             track="A")
    assert report["schema"].startswith("ceb.hosted.readiness")
    checks = {c["name"]: c for c in report["checks"]}
    assert checks["package_version"]["ok"] is True
    assert checks["db_schema_migrated"]["ok"] is True
    assert checks["official_eval_pack_trusted"]["ok"] is False  # demo pack
    assert checks["demo_pack_rejected"]["ok"] is True           # guard works
    assert checks["smoke_not_verifiable"]["ok"] is True
    assert checks["final_production_game_floor"]["ok"] is True
    assert report["ready"] is False


def test_readiness_check_ready_with_official_setup(tmp_path, official_pack,
                                                   monkeypatch):
    import ceb.jail.docker_engine as de
    import ceb.hosted.readiness as rmod
    from ceb.hosted.signing import generate_keypair

    priv = tmp_path / "priv.pem"
    pub = tmp_path / "pub.pem"
    generate_keypair(priv, pub)
    monkeypatch.setattr(de, "docker_available", lambda: True)
    monkeypatch.setattr(rmod, "_image_present", lambda image: True)

    db_path = hosted_db.init_db(tmp_path / "hosted.sqlite")
    report = rmod.readiness_check(
        db_path=str(db_path), eval_pack_dir=str(official_pack),
        public_key_path=str(pub), signing_key_path=str(priv), track="A")
    failed = [c["name"] for c in report["checks"]
              if c["required"] and not c["ok"]]
    assert report["ready"] is True, failed
    checks = {c["name"]: c for c in report["checks"]}
    # Unpinned (no allowlist): a non-blocking warning recommends pinning.
    assert checks["official_pack_pinned"]["ok"] is False
    assert checks["official_pack_pinned"]["required"] is False

    # With a matching allowlist the pack is pinned.
    from ceb.hosted.eval_pack_trust import compute_eval_pack_hash
    pinned = rmod.readiness_check(
        db_path=str(db_path), eval_pack_dir=str(official_pack),
        public_key_path=str(pub), signing_key_path=str(priv), track="A",
        official_pack_hashes=[compute_eval_pack_hash(official_pack)])
    assert {c["name"]: c for c in pinned["checks"]}["official_pack_pinned"]["ok"]


# ----- verified Track A end-to-end (opt-in docker) ----------------------------

def _jail_ready():
    import os, shutil, subprocess
    from ceb.jail.docker_engine import JAIL_IMAGE
    if os.environ.get("CEB_DOCKER_TESTS") != "1" or not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "image", "inspect", JAIL_IMAGE],
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


@pytest.mark.skipif(not _jail_ready(),
                    reason="set CEB_DOCKER_TESTS=1 with docker + jail image")
def test_verified_track_a_end_to_end_in_jail(tmp_path, official_pack):
    import os
    from ceb.hosted.signing import generate_keypair, load_public_key
    from ceb.hosted.verifier import verify_result_file
    from ceb.storage import public_artifacts

    from ceb.hosted.eval_pack_trust import compute_eval_pack_hash
    generate_keypair(tmp_path / "priv.pem", tmp_path / "pub.pem")
    os.environ["CEB_SIGNING_PRIVATE_KEY"] = str(tmp_path / "priv.pem")
    try:
        result = run_official_eval(
            run_id="v", snapshot=EXAMPLE, eval_pack_dir=str(official_pack),
            out_dir=tmp_path / "out", profile="official", engine_jail="docker",
            official_pack_hashes=[compute_eval_pack_hash(official_pack)],
            mode_config=TINY_CONFIG)
    finally:
        os.environ.pop("CEB_SIGNING_PRIVATE_KEY", None)
    assert result["verified"] is True
    assert result["metadata"]["eval_pack_trusted"] is True
    assert result["metadata"]["eval_pack_id"] == "ceb-test-2026s1"
    assert result["signature"]["algorithm"] == "ed25519"
    # Staged public artifacts were promoted.
    assert "official_result.json" in public_artifacts(tmp_path / "out")
    # Third-party verification with the operator public key is authentic.
    verdict = verify_result_file(tmp_path / "out" / "official_result.json",
                                 public_key=load_public_key(tmp_path / "pub.pem"))
    assert verdict["authentic"] is True
    assert verdict["public_official_signing"] is True


# ----- v0.3.3 API + promotion -------------------------------------------------

def test_api_track_b_leaderboard_delegates(api_client):
    # /api/leaderboard?track=B delegates to the hosted verified board (the
    # api_client DB exists) instead of claiming there is no Track B leaderboard.
    body = api_client.get("/api/leaderboard?track=B").json()
    assert "hosted/leaderboard?track=B" in body.get("note", "")
    assert body.get("verified_only") is True


def test_api_public_readiness_has_no_secrets(api_client):
    body = api_client.get("/api/hosted/readiness/public").json()
    assert body["schema"] == "ceb.hosted.readiness.public/v1"
    assert body["smoke_verifiable"] is False
    assert body["official_verifiable"] is True
    blob = json.dumps(body)
    assert "PRIVATE" not in blob and "priv" not in blob and "token" not in blob


def test_failed_leak_scan_leaves_no_public_artifacts(tmp_path, monkeypatch):
    # req 7: a failed leak scan must leave ZERO public manifest entries anywhere.
    import ceb.rounds.round_runner as rr
    from ceb.storage import public_artifacts
    from ceb.storage.artifacts import MANIFEST_NAME

    monkeypatch.setattr(rr, "make_feedback",
                        lambda report: {"leaked": "8/8/8/3k4/8/8/4Q3/4K3"})
    out = tmp_path / "out"
    with pytest.raises(OfficialEvalError, match="leak"):
        run_official_eval(run_id="x", snapshot=EXAMPLE,
                          eval_pack_dir=str(TINY_PACK), out_dir=out,
                          quick_test_mode=True)
    public = []
    for manifest in out.rglob(MANIFEST_NAME):
        public += public_artifacts(manifest.parent)
    assert public == []  # nothing promoted to public on a failed scan


# ----- v0.3.4 audit -----------------------------------------------------------

def test_malformed_ed25519_key_fails_before_eval(tmp_path, monkeypatch,
                                                 official_pack):
    # Item 3: a malformed signing key fails BEFORE scan/gate/match, leaving no
    # staged public artifacts.
    import ceb.jail.docker_engine as de
    from ceb.hosted.eval_pack_trust import compute_eval_pack_hash
    from ceb.storage import public_artifacts
    from ceb.storage.artifacts import MANIFEST_NAME

    monkeypatch.setattr(de, "ensure_ready", lambda image=de.JAIL_IMAGE: None)
    bad = tmp_path / "bad.pem"
    bad.write_text("-----BEGIN PRIVATE KEY-----\nnonsense\n-----END PRIVATE KEY-----\n")
    monkeypatch.setenv("CEB_SIGNING_PRIVATE_KEY", str(bad))
    out = tmp_path / "out"
    with pytest.raises(OfficialEvalError, match="Ed25519"):
        run_official_eval(
            run_id="x", snapshot=EXAMPLE, eval_pack_dir=str(official_pack),
            out_dir=out, profile="official", engine_jail="docker",
            official_pack_hashes=[compute_eval_pack_hash(official_pack)])
    public = []
    for manifest in out.rglob(MANIFEST_NAME):
        public += public_artifacts(manifest.parent)
    assert public == []   # nothing staged/promoted after the early key failure


def test_api_release_manifest_endpoint(api_client, tmp_path, monkeypatch):
    # Item 6: serves a configured secret-free manifest; 503 when unset.
    monkeypatch.delenv("CEB_RELEASE_MANIFEST", raising=False)
    assert api_client.get("/api/hosted/release-manifest").status_code == 503
    manifest = {"schema": "ceb.release_manifest/v1", "track": "A",
                "official_eval_pack_hash": "sha256:abc",
                "operator_public_key_fingerprint": "ed25519:beef"}
    path = tmp_path / "release.json"
    path.write_text(json.dumps(manifest))
    monkeypatch.setenv("CEB_RELEASE_MANIFEST", str(path))
    resp = api_client.get("/api/hosted/release-manifest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["operator_public_key_fingerprint"] == "ed25519:beef"
    assert "PRIVATE" not in json.dumps(body)


def test_result_bundle_includes_release_manifest_and_fingerprint(tmp_path):
    # Item 7: the selected-only bundle includes the release manifest + key
    # fingerprint, and stays secret-free.
    import zipfile
    from ceb.hosted.result_bundle import export_result_bundle

    db_path = hosted_db.init_db(tmp_path / "hosted.sqlite")
    final_id = _register_result_with_artifacts(
        db_path, "run", job_id=3, mode="final_production", score=700.0,
        verified=True, profile="final-production", grade="verified-final-production",
        public_names=("official_result.json", "feedback.json"),
        private_names=("scan_report.json",))
    rel = tmp_path / "release.json"
    rel.write_text(json.dumps({"schema": "ceb.release_manifest/v1", "track": "A",
                               "operator_public_key_fingerprint": "ed25519:cafe"}))
    conn = hosted_db.connect(db_path)
    try:
        out, manifest = export_result_bundle(
            conn, "run", tmp_path / "bundle.zip", db_path=db_path,
            release_manifest_path=str(rel), public_key_fingerprint="ed25519:cafe")
    finally:
        conn.close()
    assert manifest["selected_result_id"] == final_id
    assert manifest["release_manifest_included"] is True
    assert manifest["operator_public_key_fingerprint"] == "ed25519:cafe"
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        verify = zf.read("VERIFY.txt").decode()
    assert "release_manifest.json" in names
    assert "ed25519:cafe" in verify
    assert not any("scan_report.json" in n for n in names)


def test_malformed_key_on_smoke_path_degrades_to_unsigned(tmp_path, monkeypatch):
    # Review #4: a malformed key on a diagnostic (smoke) path must not crash —
    # it degrades to unsigned (verified paths load-validate the key up front).
    bad = tmp_path / "bad.pem"
    bad.write_text("-----BEGIN PRIVATE KEY-----\nnope\n-----END PRIVATE KEY-----\n")
    monkeypatch.setenv("CEB_SIGNING_PRIVATE_KEY", str(bad))
    result = run_official_eval(
        run_id="s", snapshot=EXAMPLE, eval_pack_dir=str(TINY_PACK),
        out_dir=tmp_path / "out", quick_test_mode=True)
    assert result["verified"] is False
    assert result["signature"]["status"] == "unsigned"


def test_result_bundle_rejects_bad_release_manifest(tmp_path):
    # Review #8: a non-JSON --release-manifest fails cleanly with no partial zip.
    from ceb.hosted.result_bundle import export_result_bundle, ResultBundleError
    db_path = hosted_db.init_db(tmp_path / "hosted.sqlite")
    _register_result_with_artifacts(
        db_path, "run", job_id=1, mode="final_production", score=700.0,
        verified=True, profile="final-production", grade="verified-final-production",
        public_names=("official_result.json",))
    bad = tmp_path / "bad.json"
    bad.write_text("-----BEGIN PRIVATE KEY-----\nnot json\n")
    out = tmp_path / "bundle.zip"
    conn = hosted_db.connect(db_path)
    try:
        with pytest.raises(ResultBundleError, match="JSON"):
            export_result_bundle(conn, "run", out, db_path=db_path,
                                 release_manifest_path=str(bad))
    finally:
        conn.close()
    assert not out.exists()    # no partial bundle left behind
