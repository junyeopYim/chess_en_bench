"""Tests for the Track A public gate."""

import shutil
from pathlib import Path

import pytest

from ceb.gate.gate_runner import run_gate

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPO_ROOT / "examples" / "submissions"


def _make_workspace(tmp_path, engine_script):
    """Build a throwaway workspace around one broken-engine script."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    shutil.copy(engine_script, workspace / "main.py")
    wrapper = workspace / "engine"
    wrapper.write_text('#!/usr/bin/env bash\nexec python3 "$(dirname "$0")/main.py"\n')
    wrapper.chmod(0o755)
    return workspace


def test_gate_passes_minimal_engine():
    report = run_gate(EXAMPLES / "minimal_uci_engine_python", root=REPO_ROOT)
    statuses = {c.check_id: c.status for c in report.checks}
    assert report.passed, report.human_summary()
    assert statuses["handshake"] == "pass"
    assert statuses["bestmove"] == "pass"
    assert statuses["perft"] == "pass"  # example engine implements the extension
    assert statuses["mini_match"] == "pass"


def test_gate_fails_illegal_move_engine(tmp_path):
    workspace = _make_workspace(
        tmp_path, EXAMPLES / "broken_engine_examples" / "illegal_move_engine.py")
    report = run_gate(workspace, root=REPO_ROOT)
    statuses = {c.check_id: c.status for c in report.checks}
    assert not report.passed
    assert statuses["bestmove"] == "fail"
    assert statuses["mini_match"] == "skip"  # heavy checks skipped after failure


def test_gate_fails_timeout_engine(tmp_path):
    workspace = _make_workspace(
        tmp_path, EXAMPLES / "broken_engine_examples" / "timeout_engine.py")
    report = run_gate(workspace, root=REPO_ROOT)
    statuses = {c.check_id: c.status for c in report.checks}
    assert not report.passed
    assert statuses["bestmove"] == "fail"


def test_gate_fails_missing_workspace(tmp_path):
    report = run_gate(tmp_path / "does_not_exist", root=REPO_ROOT)
    assert not report.passed
    assert report.checks[0].check_id == "format"
    assert report.checks[0].status == "fail"


def test_gate_never_echoes_fens_from_bad_pack_rows():
    """Defense in depth: even if an invalid FEN row reaches the gate (packs
    validate at load, but a pack object can be built directly), the failure
    detail quotes the row id only — never the position."""
    from ceb.eval_pack import EvalPack

    secret_placement = "2r3k1/5ppp/8/8/8/8/5PPP/2R3K1"
    pack = EvalPack(
        name="direct", source="public+private",
        fens=[{"id": "secret_row", "fen": secret_placement + " w - - 0 x"}],
        perft=[], openings=[])
    report = run_gate(EXAMPLES / "minimal_uci_engine_python", root=REPO_ROOT,
                      quick_match=False, eval_pack=pack)
    assert not report.passed
    dumped = report.to_json() + report.human_summary()
    assert "secret_row" in dumped
    assert secret_placement not in dumped


def test_gate_report_json_shape():
    report = run_gate(EXAMPLES / "minimal_uci_engine_python", root=REPO_ROOT,
                      quick_match=False)
    data = report.to_dict()
    assert data["schema"] == "ceb.gate.report/v1"
    assert data["track"] == "A"
    assert isinstance(data["passed"], bool)
    assert {c["id"] for c in data["checks"]} >= {
        "format", "build", "handshake", "position", "bestmove", "perft", "time"}
