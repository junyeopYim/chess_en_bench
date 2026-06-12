"""Tests for the anti-cheating scanners (P0.7)."""

import os
from pathlib import Path

import pytest

from ceb.cli import main
from ceb.scan import scan_track_b, scan_workspace

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples" / "submissions" / "minimal_uci_engine_python"


def _workspace(tmp_path, engine_body):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "engine.py").write_text(engine_body)
    wrapper = workspace / "engine"
    wrapper.write_text('#!/usr/bin/env bash\nexec python3 "$(dirname "$0")/engine.py"\n')
    wrapper.chmod(0o755)
    return workspace


def _rules(report):
    return {f["rule"] for f in report["findings"] if f["severity"] == "fail"}


def test_minimal_engine_passes():
    report = scan_workspace(EXAMPLE)
    assert report["passed"], report["findings"]


def test_python_chess_import_fails(tmp_path):
    report = scan_workspace(_workspace(tmp_path, "import chess\n"))
    assert not report["passed"]
    assert "external-chess-lib" in _rules(report)


def test_stockfish_invocation_fails(tmp_path):
    body = 'import subprocess\nsubprocess.Popen(["stockfish"])\n'
    report = scan_workspace(_workspace(tmp_path, body))
    assert not report["passed"]
    assert {"external-engine", "process-spawn"} <= _rules(report)


def test_network_usage_fails(tmp_path):
    for i, body in enumerate(("import socket\n", "import requests\n",
                              "from urllib import request\n")):
        sub = tmp_path / ("net_%d" % i)
        sub.mkdir()
        report = scan_workspace(_workspace(sub, body))
        assert not report["passed"], body
        assert "network" in _rules(report), body


def test_harness_fingerprinting_fails(tmp_path):
    body = 'import os\npath = os.environ.get("CEB_PRIVATE_EVAL_DIR")\n'
    report = scan_workspace(_workspace(tmp_path, body))
    assert not report["passed"]
    assert "harness-fingerprinting" in _rules(report)


def test_symlink_escape_fails(tmp_path):
    workspace = _workspace(tmp_path, "x = 1\n")
    os.symlink("/etc/passwd", workspace / "sneaky")
    report = scan_workspace(workspace)
    assert not report["passed"]
    assert "symlink-escape" in _rules(report)


def test_book_extension_and_oversize_fail(tmp_path):
    workspace = _workspace(tmp_path, "x = 1\n")
    (workspace / "book.bin").write_bytes(b"\x00\x01")
    (workspace / "table.py").write_text("data = []\n" + "y" * 1)
    (workspace / "huge.py").write_text("z = 1\n" * 1)
    (workspace / "huge.py").write_bytes(b"a" * (2 * 1024 * 1024 + 1))
    report = scan_workspace(workspace)
    rules = _rules(report)
    assert "book-or-tablebase" in rules
    assert "oversized-file" in rules


def test_cli_scan_workspace():
    assert main(["scan", "workspace", "--track", "A",
                 "--workspace", str(EXAMPLE)]) == 0


def _tree(root, files):
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def test_track_b_forbidden_change_fails(tmp_path):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    for tree in (baseline, candidate):
        _tree(tree, {"src/search.cpp": "int d = 1;\n",
                     "src/evaluate.cpp": "int e = 0;\n"})
    _tree(candidate, {"src/evaluate.cpp": "int e = 9;\n"})
    report = scan_track_b(baseline, candidate, root=REPO_ROOT)
    assert not report["passed"]
    assert "diff-whitelist" in _rules(report)


def test_track_b_fingerprinting_and_symlink_fail(tmp_path):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    for tree in (baseline, candidate):
        _tree(tree, {"src/search.cpp": "int d = 1;\n"})
    _tree(candidate, {"src/search.cpp":
                      'if (getenv("CEB_OPPONENT")) depth += 1;\n'})
    os.symlink("/etc", candidate / "link")
    report = scan_track_b(baseline, candidate, root=REPO_ROOT)
    rules = _rules(report)
    assert "harness-fingerprinting" in rules
    assert "symlink" in rules


def test_track_b_clean_allowed_change_passes(tmp_path):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    for tree in (baseline, candidate):
        _tree(tree, {"src/search.cpp": "int d = 1;\n"})
    _tree(candidate, {"src/search.cpp": "int d = 2;\n"})
    report = scan_track_b(baseline, candidate, root=REPO_ROOT)
    assert report["passed"], report["findings"]
