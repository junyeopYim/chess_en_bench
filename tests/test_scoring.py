"""Tests for Elo math and track scoring."""

import math

import pytest

from ceb.scoring import elo
from ceb.scoring.track_a import compute_round_score, compute_leaderboard
from ceb.scoring.track_b import compute_delta_elo_report


def test_score_rate_basics():
    assert elo.score_rate(5, 0, 5) == 0.5
    assert elo.score_rate(0, 10, 0) == 0.5
    assert elo.score_rate(3, 2, 1) == pytest.approx(4 / 6)
    with pytest.raises(ValueError):
        elo.score_rate(0, 0, 0)


def test_delta_elo_known_values():
    assert elo.delta_elo(0.5) == pytest.approx(0.0)
    assert elo.delta_elo(0.75) == pytest.approx(-400 * math.log10(1 / 0.75 - 1))
    assert elo.delta_elo(0.75) == pytest.approx(190.85, abs=0.01)
    assert elo.delta_elo(0.25) == pytest.approx(-190.85, abs=0.01)


def test_clamp_prevents_infinities():
    rate = elo.clamp_rate(1.0, games=10)
    assert 0.0 < rate < 1.0
    assert math.isfinite(elo.delta_elo(rate))
    assert math.isfinite(elo.delta_elo_from_wdl(10, 0, 0))
    assert math.isfinite(elo.delta_elo_from_wdl(0, 0, 10))


def test_delta_elo_ci_ordering():
    lo, mid, hi = elo.delta_elo_ci(12, 4, 4)
    assert lo <= mid <= hi
    assert mid == pytest.approx(elo.delta_elo_from_wdl(12, 4, 4))


def _match_report(opponent, wins, draws, losses, faults=None):
    return {
        "opponent": opponent,
        "totals": {"wins": wins, "draws": draws, "losses": losses},
        "candidate_faults": faults or {"illegal": 0, "timeout": 0, "crash": 0},
    }


def test_track_a_round_score():
    reports = [
        _match_report("BenchRandom", 2, 0, 0),
        _match_report("BenchMaterial1", 0, 1, 1),
    ]
    score = compute_round_score(reports)
    assert score["schema"] == "ceb.score.track_a/v1"
    by_opp = {e["opponent"]: e for e in score["per_opponent"]}
    assert by_opp["BenchRandom"]["delta_elo"] > 0
    assert by_opp["BenchMaterial1"]["delta_elo"] < 0
    assert score["penalty_points"] == 0
    assert score["final_score"] == score["ladder_score"]


def test_track_a_penalties_subtract():
    clean = compute_round_score([_match_report("BenchRandom", 1, 0, 1)])
    faulty = compute_round_score([
        _match_report("BenchRandom", 1, 0, 1,
                      {"illegal": 1, "timeout": 2, "crash": 1}),
    ])
    assert faulty["penalty_points"] == 30 + 2 * 15 + 25
    assert faulty["final_score"] == clean["final_score"] - faulty["penalty_points"]


def test_track_b_delta_elo_report():
    report = compute_delta_elo_report(12, 4, 4)
    assert report["schema"] == "ceb.score.track_b/v1"
    assert report["delta_elo"] > 0
    lo, hi = report["delta_elo_ci95"]
    assert lo <= report["delta_elo"] <= hi
    assert report["final_delta_elo"] == report["delta_elo"]  # no faults

    even = compute_delta_elo_report(5, 0, 5)
    assert even["delta_elo"] == pytest.approx(0.0)


def test_leaderboard_empty_and_sorted(tmp_path):
    board = compute_leaderboard(tmp_path)
    assert board["entries"] == []

    import json
    for run_id, score in (("alpha", 700.0), ("beta", 900.0), ("gamma", None)):
        run_dir = tmp_path / run_id
        run_dir.mkdir()
        rounds = [] if score is None else [
            {"round": 1, "mode": "official", "score": score}]
        (run_dir / "state.json").write_text(json.dumps({
            "schema": "ceb.run.state/v1", "run_id": run_id, "track": "A",
            "gate": {"passed": True}, "rounds": rounds,
        }))
    board = compute_leaderboard(tmp_path)
    assert [e["run_id"] for e in board["entries"]] == ["beta", "alpha", "gamma"]
    assert board["entries"][0]["score"] == 900.0
