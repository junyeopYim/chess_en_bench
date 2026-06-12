"""Tests for the Track B candidate-vs-baseline round runner."""

from pathlib import Path

import pytest

from ceb.match.opponents import opponent_command
from ceb.track_b.round_runner import run_track_b_round, TrackBRoundError

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ENGINE = REPO_ROOT / "examples" / "submissions" / "minimal_uci_engine_python" / "engine"


def _make_tree(root, files):
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def test_diff_violation_prevents_scoring(tmp_path):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    for tree in (baseline, candidate):
        _make_tree(tree, {"src/search.cpp": "int d = 1;\n",
                          "src/evaluate.cpp": "int e = 0;\n"})
    _make_tree(candidate, {"src/evaluate.cpp": "int e = 9;\n"})  # forbidden

    with pytest.raises(TrackBRoundError, match="diff whitelist") as excinfo:
        run_track_b_round(
            [str(EXAMPLE_ENGINE)], opponent_command("BenchRandom"),
            baseline_src=baseline, candidate_src=candidate,
            games=2, runs_root=tmp_path / "runs")
    assert excinfo.value.diff_report is not None
    assert not excinfo.value.diff_report["passed"]
    # No games were played, nothing was scored.
    assert not (tmp_path / "runs").exists() or \
        not list((tmp_path / "runs").rglob("report.json"))


def test_handshake_failure_aborts(tmp_path):
    bad = tmp_path / "not_an_engine"
    bad.write_text("#!/usr/bin/env bash\nexit 1\n")
    bad.chmod(0o755)
    with pytest.raises(TrackBRoundError, match="handshake"):
        run_track_b_round([str(bad)], opponent_command("BenchRandom"),
                          games=2, runs_root=tmp_path / "runs")


def test_tiny_match_produces_valid_report(tmp_path):
    report, feedback = run_track_b_round(
        [str(EXAMPLE_ENGINE)], opponent_command("BenchRandom"),
        round_number=1, run_id="tb_test", games=2, movetime_ms=30,
        max_plies=20, runs_root=tmp_path)

    assert report["schema"] == "ceb.track_b.round.report/v1"
    assert report["uci_options"]["Threads"] == "1"
    totals = report["totals"]
    assert totals["wins"] + totals["draws"] + totals["losses"] == 2
    assert len(report["openings_used"]) >= 1

    score = report["score"]
    assert score["schema"] == "ceb.score.track_b/v1"
    assert score["games"] == 2
    assert score["delta_elo"] is not None
    lo, hi = score["delta_elo_ci95"]
    assert lo <= score["delta_elo"] <= hi

    assert feedback["schema"] == "ceb.track_b.feedback/v1"
    assert "games" in feedback and feedback["games"] == 2
    assert "moves" not in feedback  # sanitized: aggregates only

    round_dir = tmp_path / "tb_test" / "track_b_round_1"
    for name in ("report.json", "feedback.json", "match.json", "games.txt"):
        assert (round_dir / name).is_file()
