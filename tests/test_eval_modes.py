"""Tests for eval modes + CI fields + leaderboard final-eval policy (P0.6)."""

import json
from pathlib import Path

import pytest

from ceb.rounds.round_runner import (
    DEFAULT_ROUND_MODES, MODE_FINAL, MODE_FINAL_PRODUCTION, MODE_OFFICIAL,
    MODE_QUICK, run_round)
from ceb.scoring.track_a import compute_leaderboard

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples" / "submissions" / "minimal_uci_engine_python"

TINY = {"opponents": ["BenchRandom"], "games_per_opponent": 2,
        "movetime_ms": 30, "max_plies": 30, "openings_limit": 1}


def test_three_modes_distinguished(tmp_path):
    quick, _, _ = run_round(EXAMPLE, 1, mode=MODE_QUICK, run_id="m",
                            runs_root=tmp_path, mode_config=TINY)
    official, _, _ = run_round(EXAMPLE, 2, mode=MODE_OFFICIAL, run_id="m",
                               runs_root=tmp_path, mode_config=TINY)
    final, _, state = run_round(EXAMPLE, 3, mode=MODE_FINAL, run_id="m",
                                runs_root=tmp_path, mode_config=TINY)
    assert quick["mode"] == "quick" and quick["strict_gate"] is False
    assert official["mode"] == "official_round" and official["strict_gate"]
    assert final["mode"] == "final_eval" and final["strict_gate"]
    # Only the official_round consumes budget; quick and final do not.
    assert state.budget_used == 1


def test_score_has_confidence_interval(tmp_path):
    report, feedback, _ = run_round(EXAMPLE, 1, mode=MODE_QUICK, run_id="ci",
                                    runs_root=tmp_path, mode_config=TINY)
    overall = report["score"]["overall"]
    assert overall["games"] == 2
    assert overall["score_rate"] is not None
    assert overall["delta_elo_vs_pool"] is not None
    lo, hi = overall["delta_elo_ci95"]
    assert lo <= overall["delta_elo_vs_pool"] <= hi
    assert "illegal" in report["score"]["faults"]
    assert report["score"]["opening_coverage"]["openings_played"] >= 1
    # Per-opponent breakdown present.
    assert report["score"]["per_opponent"][0]["opponent"] == "BenchRandom"
    assert feedback["overall"] == overall


def test_leaderboard_prefers_final_eval(tmp_path):
    # final_eval (lower score) must outrank a higher official_round.
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "state.json").write_text(json.dumps({
        "schema": "ceb.run.state/v1", "run_id": "run", "track": "A",
        "gate": {"passed": True},
        "rounds": [
            {"round": 1, "mode": "quick", "score": 2000.0},
            {"round": 2, "mode": "official_round", "score": 900.0},
            {"round": 3, "mode": "final_eval", "score": 700.0},
        ],
    }))
    board = compute_leaderboard(tmp_path)
    entry = board["entries"][0]
    assert entry["best_round"]["mode"] == "final_eval"
    assert entry["score"] == 700.0
    assert entry["verified"] is False


def test_leaderboard_falls_back_to_official_then_excludes_quick(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "state.json").write_text(json.dumps({
        "schema": "ceb.run.state/v1", "run_id": "run", "track": "A",
        "gate": {"passed": True},
        "rounds": [
            {"round": 1, "mode": "quick", "score": 2000.0},
            {"round": 2, "mode": "official_round", "score": 850.0},
        ],
    }))
    official = compute_leaderboard(tmp_path)
    assert official["entries"][0]["score"] == 850.0
    diagnostic = compute_leaderboard(tmp_path, include_quick=True)
    assert diagnostic["entries"][0]["score"] == 2000.0


def test_final_production_mode_is_production_scale():
    # P0.3: the production profile must default to a leaderboard-quality game
    # count (>= 2000 total across the opponent pool), separate from CI/smoke.
    cfg = DEFAULT_ROUND_MODES[MODE_FINAL_PRODUCTION]
    total_games = len(cfg["opponents"]) * cfg["games_per_opponent"]
    assert total_games >= 2000, total_games
    assert cfg["movetime_ms"] >= 1000


def test_final_production_runs_strict_and_is_final_tier(tmp_path):
    # Exercised with a tiny override (the configured defaults must NEVER run in
    # CI); it is strict, final-tier, and consumes no official budget.
    report, _, state = run_round(EXAMPLE, 1, mode=MODE_FINAL_PRODUCTION,
                                 run_id="fp", runs_root=tmp_path,
                                 mode_config=TINY)
    assert report["mode"] == "final_production"
    assert report["strict_gate"] is True
    assert state.budget_used == 0  # final tiers never consume budget

    run_dir = tmp_path / "fp"
    (run_dir / "state.json").write_text(json.dumps({
        "schema": "ceb.run.state/v1", "run_id": "fp", "track": "A",
        "gate": {"passed": True},
        "rounds": [
            {"round": 1, "mode": "official_round", "score": 1500.0},
            {"round": 2, "mode": "final_production", "score": 900.0},
        ],
    }))
    board = compute_leaderboard(tmp_path)
    entry = next(e for e in board["entries"] if e["run_id"] == "fp")
    assert entry["best_round"]["mode"] == "final_production"
    assert entry["score"] == 900.0  # final-tier outranks the higher official


def test_legacy_official_mode_still_counts(tmp_path):
    run_dir = tmp_path / "legacy"
    run_dir.mkdir()
    (run_dir / "state.json").write_text(json.dumps({
        "schema": "ceb.run.state/v1", "run_id": "legacy", "track": "A",
        "gate": {"passed": True},
        "rounds": [{"round": 1, "mode": "official", "score": 600.0}],
    }))
    board = compute_leaderboard(tmp_path)
    assert board["entries"][0]["score"] == 600.0
