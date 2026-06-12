"""CLI smoke tests (argparse wiring + non-engine commands)."""

from pathlib import Path

import pytest

from ceb.cli import build_parser, main

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v02_flags_parse():
    parser = build_parser()
    args = parser.parse_args(["gate", "run", "--workspace", "x", "--strict",
                              "--sandbox", "docker", "--eval-pack", "p"])
    assert args.strict and args.sandbox == "docker" and args.eval_pack == "p"
    args = parser.parse_args(["round", "run", "--workspace", "x", "--round",
                              "1", "--quick", "--sandbox", "none"])
    assert args.sandbox == "none"
    args = parser.parse_args(["leaderboard", "compute", "--include-quick"])
    assert args.include_quick
    args = parser.parse_args(["track-b", "round", "run",
                              "--candidate-engine", "a",
                              "--baseline-engine", "b", "--games", "4"])
    assert args.games == 4


def test_doctor_runs(capsys):
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "chess_en_bench doctor" in out
    assert "repo root" in out


def test_version_flag():
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0


def test_leaderboard_compute_empty(tmp_path, capsys):
    assert main(["leaderboard", "compute", "--track", "A",
                 "--results", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "no scored runs" in out
    assert "official rounds only" in out
    assert main(["leaderboard", "compute", "--track", "A",
                 "--results", str(tmp_path), "--include-quick"]) == 0
    assert "quick rounds INCLUDED" in capsys.readouterr().out


def test_workspace_prepare(tmp_path, capsys):
    rc = main(["workspace", "prepare", "--track", "A", "--run-id", "demo",
               "--runs-dir", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "demo" / "workspace" / "README.md").is_file()
    assert (tmp_path / "demo" / "state.json").is_file()
    assert (tmp_path / "demo" / "instructions.md").is_file()


def test_track_b_status_without_stockfish(capsys):
    assert main(["track-b", "status"]) == 0
    out = capsys.readouterr().out
    assert "sf_18" in out


def test_track_b_check_diff(tmp_path, capsys):
    baseline = tmp_path / "baseline" / "src"
    candidate = tmp_path / "candidate" / "src"
    baseline.mkdir(parents=True)
    candidate.mkdir(parents=True)
    for d in (baseline, candidate):
        (d / "search.cpp").write_text("int depth = 1;\n")
        (d / "evaluate.cpp").write_text("int eval = 0;\n")
    # Allowed change only -> pass
    (candidate / "search.cpp").write_text("int depth = 2;\n")
    assert main(["track-b", "check-diff",
                 "--baseline", str(tmp_path / "baseline"),
                 "--candidate", str(tmp_path / "candidate")]) == 0
    # Forbidden change -> fail
    (candidate / "evaluate.cpp").write_text("int eval = 9;\n")
    assert main(["track-b", "check-diff",
                 "--baseline", str(tmp_path / "baseline"),
                 "--candidate", str(tmp_path / "candidate")]) == 2


def test_gate_run_cli_on_example(capsys):
    workspace = REPO_ROOT / "examples" / "submissions" / "minimal_uci_engine_python"
    rc = main(["gate", "run", "--track", "A", "--workspace", str(workspace),
               "--no-match"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "Gate result: PASSED" in out
