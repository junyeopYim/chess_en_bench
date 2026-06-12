"""Tests for the strict gate (perft mandatory) and its round precondition."""

from pathlib import Path

import pytest

from ceb.gate.gate_runner import run_gate
from ceb.rounds.round_runner import run_round, RoundError
from ceb.rounds.state import RunState

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples" / "submissions" / "minimal_uci_engine_python"


@pytest.fixture()
def no_perft_workspace(tmp_path):
    """The example engine with its 'go perft' support disabled: a fully
    legal engine that treats 'go perft N' as a normal search."""
    workspace = tmp_path / "no_perft"
    workspace.mkdir()
    source = (EXAMPLE / "engine.py").read_text()
    patched = source.replace('if len(tokens) >= 3 and tokens[1] == "perft":',
                             "if False:")
    assert patched != source, "engine.py perft branch not found"
    (workspace / "main.py").write_text(patched)
    wrapper = workspace / "engine"
    wrapper.write_text('#!/usr/bin/env bash\nexec python3 "$(dirname "$0")/main.py"\n')
    wrapper.chmod(0o755)
    return workspace


def test_minimal_engine_passes_strict_gate():
    report = run_gate(EXAMPLE, root=REPO_ROOT, strict=True, quick_match=False)
    assert report.passed, report.human_summary()
    assert report.to_dict()["strict"] is True


def test_missing_perft_warns_public_but_fails_strict(no_perft_workspace):
    public = run_gate(no_perft_workspace, root=REPO_ROOT, quick_match=False)
    statuses = {c.check_id: c.status for c in public.checks}
    assert public.passed
    assert statuses["perft"] == "warn"

    strict = run_gate(no_perft_workspace, root=REPO_ROOT, strict=True,
                      quick_match=False)
    statuses = {c.check_id: c.status for c in strict.checks}
    assert not strict.passed
    assert statuses["perft"] == "fail"


def test_official_round_aborts_before_spending_budget(no_perft_workspace, tmp_path):
    runs_root = tmp_path / "runs"
    with pytest.raises(RoundError, match="no budget"):
        run_round(no_perft_workspace, 1, quick=False, run_id="strict_fail",
                  runs_root=runs_root)
    state = RunState.load_or_create(runs_root, "strict_fail")
    assert state.budget_used == 0
    assert state.gate["passed"] is False
    assert not (runs_root / "strict_fail" / "round_1").exists()
