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


def test_gate_report_json_shape():
    report = run_gate(EXAMPLES / "minimal_uci_engine_python", root=REPO_ROOT,
                      quick_match=False)
    data = report.to_dict()
    assert data["schema"] == "ceb.gate.report/v1"
    assert data["track"] == "A"
    assert isinstance(data["passed"], bool)
    assert {c["id"] for c in data["checks"]} >= {
        "format", "build", "handshake", "position", "bestmove", "perft", "time"}
