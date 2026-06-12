"""Tests for the official leaderboard policy (quick rounds excluded)."""

import json

from ceb.scoring.track_a import compute_leaderboard


def _write_state(runs_dir, run_id, rounds, track="A"):
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "state.json").write_text(json.dumps({
        "schema": "ceb.run.state/v1",
        "run_id": run_id,
        "track": track,
        "gate": {"passed": True},
        "rounds": rounds,
    }))


def test_quick_rounds_excluded_by_default(tmp_path):
    # High-scoring quick round must not beat the lower official round.
    _write_state(tmp_path, "mixed", [
        {"round": 1, "mode": "quick", "score": 1500.0},
        {"round": 2, "mode": "official", "score": 700.0},
    ])
    board = compute_leaderboard(tmp_path)
    assert board["include_quick"] is False
    entry = board["entries"][0]
    assert entry["score"] == 700.0
    assert entry["best_round"]["mode"] == "official"
    assert entry["official_rounds_played"] == 1


def test_include_quick_is_diagnostic_opt_in(tmp_path):
    _write_state(tmp_path, "mixed", [
        {"round": 1, "mode": "quick", "score": 1500.0},
        {"round": 2, "mode": "official", "score": 700.0},
    ])
    board = compute_leaderboard(tmp_path, include_quick=True)
    assert board["include_quick"] is True
    entry = board["entries"][0]
    assert entry["score"] == 1500.0
    assert entry["best_round"]["mode"] == "quick"


def test_quick_only_run_has_no_official_score(tmp_path):
    _write_state(tmp_path, "quick_only", [
        {"round": 1, "mode": "quick", "score": 900.0},
    ])
    _write_state(tmp_path, "official_run", [
        {"round": 1, "mode": "official", "score": 500.0},
    ])
    board = compute_leaderboard(tmp_path)
    by_id = {e["run_id"]: e for e in board["entries"]}
    assert by_id["quick_only"]["score"] is None
    assert by_id["official_run"]["score"] == 500.0
    # Scored entries rank above unscored ones.
    assert board["entries"][0]["run_id"] == "official_run"


def test_legacy_rounds_without_mode_count_as_official(tmp_path):
    _write_state(tmp_path, "legacy", [{"round": 1, "score": 650.0}])
    board = compute_leaderboard(tmp_path)
    assert board["entries"][0]["score"] == 650.0
