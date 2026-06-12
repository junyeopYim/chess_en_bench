"""Track A scoring: ladder score from matches against the opponent pool.

For each opponent the candidate's performance rating is
    opponent_rating + delta_elo(clamped score rate)
and the ladder score is the mean performance across opponents, minus
fault penalties. Nominal opponent ratings and penalty weights live in
tracks/a_from_scratch/scoring.yaml.
"""

import json
from pathlib import Path

from ceb.scoring import elo

DEFAULT_OPPONENT_RATINGS = {
    "BenchRandom": 400,
    "BenchGreedyCapture": 600,
    "BenchMaterial1": 800,
    "BenchPST1": 1000,
    "BenchMiniMax2": 1200,
    "BenchAlphaBeta3": 1400,
}

DEFAULT_PENALTIES = {"illegal_move": 30, "timeout": 15, "crash": 25}

_FAULT_TO_PENALTY_KEY = {"illegal": "illegal_move", "timeout": "timeout", "crash": "crash"}


def compute_round_score(match_reports, opponent_ratings=None, penalties=None):
    """Aggregate internal-runner match reports into a round score dict."""
    opponent_ratings = opponent_ratings or DEFAULT_OPPONENT_RATINGS
    penalties = penalties or DEFAULT_PENALTIES

    per_opponent = []
    fault_totals = {"illegal": 0, "timeout": 0, "crash": 0}
    for report in match_reports:
        totals = report["totals"]
        wins, draws, losses = totals["wins"], totals["draws"], totals["losses"]
        games = wins + draws + losses
        opponent = report["opponent"]
        rating = opponent_ratings.get(opponent, 800)
        entry = {
            "opponent": opponent,
            "opponent_rating": rating,
            "wins": wins, "draws": draws, "losses": losses, "games": games,
        }
        if games > 0:
            rate = elo.clamp_rate(elo.score_rate(wins, draws, losses), games)
            entry["score_rate"] = round(rate, 4)
            entry["delta_elo"] = round(elo.delta_elo(rate), 1)
            entry["performance"] = round(rating + entry["delta_elo"], 1)
        else:
            entry["score_rate"] = None
            entry["delta_elo"] = None
            entry["performance"] = None
        per_opponent.append(entry)
        for kind in fault_totals:
            fault_totals[kind] += report.get("candidate_faults", {}).get(kind, 0)

    rated = [e["performance"] for e in per_opponent if e["performance"] is not None]
    ladder = sum(rated) / len(rated) if rated else None
    penalty_total = sum(
        fault_totals[kind] * penalties.get(key, 0)
        for kind, key in _FAULT_TO_PENALTY_KEY.items()
    )
    final = round(ladder - penalty_total, 1) if ladder is not None else None
    return {
        "schema": "ceb.score.track_a/v1",
        "per_opponent": per_opponent,
        "faults": fault_totals,
        "penalty_points": penalty_total,
        "ladder_score": round(ladder, 1) if ladder is not None else None,
        "final_score": final,
    }


def compute_leaderboard(results_dir, track="A", include_quick=False):
    """Scan runs/*/state.json + round reports and rank by best valid round.

    Official policy: only official rounds count. include_quick=True is a
    diagnostic mode that also considers quick rounds; never use it for
    official rankings.

    Returns {"schema": ..., "track": ..., "entries": [...]}, best first.
    """
    results_dir = Path(results_dir)
    entries = []
    if results_dir.is_dir():
        for state_path in sorted(results_dir.glob("*/state.json")):
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if state.get("track", "A").upper() != track.upper():
                continue
            rounds = state.get("rounds", [])
            best = None
            for rnd in rounds:
                score = rnd.get("score")
                mode = rnd.get("mode", "official")
                if score is None:
                    continue
                if not include_quick and mode != "official":
                    continue
                if best is None or score > best["score"]:
                    best = {"round": rnd.get("round"), "score": score,
                            "mode": mode}
            entries.append({
                "run_id": state.get("run_id", state_path.parent.name),
                "workspace": state.get("workspace"),
                "gate_passed": bool(state.get("gate", {}).get("passed")),
                "rounds_played": len(rounds),
                "official_rounds_played": sum(
                    1 for r in rounds if r.get("mode", "official") == "official"),
                "best_round": best,
                "score": best["score"] if best else None,
            })
    entries.sort(key=lambda e: (e["score"] is None, -(e["score"] or 0)))
    return {"schema": "ceb.leaderboard/v1", "track": track.upper(),
            "include_quick": include_quick, "entries": entries}
