"""Tests for run_id inference on prepared workspaces (P0.2) plus the
quick-round integration smoke (openings + artifacts land under the run id)."""

import json
import shutil
from pathlib import Path

from ceb.cli import main
from ceb.rounds.round_runner import default_run_id, run_round

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples" / "submissions" / "minimal_uci_engine_python"


def test_plain_workspace_uses_directory_name(tmp_path):
    workspace = tmp_path / "my_engine"
    workspace.mkdir()
    assert default_run_id(workspace) == "my_engine"


def test_prepared_workspace_uses_parent_run_id(tmp_path):
    run_dir = tmp_path / "demo"
    workspace = run_dir / "workspace"
    workspace.mkdir(parents=True)
    (run_dir / "state.json").write_text("{}")
    assert default_run_id(workspace) == "demo"


def test_bare_workspace_dir_without_state_keeps_old_behavior(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    assert default_run_id(workspace) == "workspace"


def test_quick_round_on_prepared_workspace_lands_under_run_id(tmp_path):
    # ceb workspace prepare --run-id demo, then round run WITHOUT --run-id.
    assert main(["workspace", "prepare", "--track", "A", "--run-id", "demo",
                 "--runs-dir", str(tmp_path)]) == 0
    workspace = tmp_path / "demo" / "workspace"
    for name in ("engine.py", "build.sh", "engine"):
        shutil.copy(EXAMPLE / name, workspace / name)
    (workspace / "engine").chmod(0o755)
    (workspace / "build.sh").chmod(0o755)

    report, feedback, state = run_round(workspace, 1, quick=True,
                                        runs_root=tmp_path)

    assert report["run_id"] == "demo"
    assert state.run_id == "demo"
    report_path = tmp_path / "demo" / "round_1" / "report.json"
    assert report_path.is_file()
    assert not (tmp_path / "workspace").exists()  # the old wrong location

    # Quick rounds are free and non-strict.
    data = json.loads(report_path.read_text())
    assert data["mode"] == "quick"
    assert data["strict_gate"] is False
    assert state.budget_used == 0

    # P0.4: the round drew from the opening suite, not just startpos.
    assert len(data["openings_used"]) >= 2
    match_files = list((tmp_path / "demo" / "round_1").glob("match_vs_*.json"))
    start_fens = set()
    for path in match_files:
        for game in json.loads(path.read_text())["games"]:
            start_fens.add(game["start_fen"])
    assert len(start_fens) >= 2
