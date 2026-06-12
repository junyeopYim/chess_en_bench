"""Track B scoring: delta Elo of a candidate Stockfish build vs the pinned
baseline, from candidate-vs-baseline W/D/L."""

from ceb.scoring import elo

DEFAULT_PENALTIES = {"illegal_move": 30, "timeout": 15, "crash": 25}

_FAULT_TO_PENALTY_KEY = {"illegal": "illegal_move", "timeout": "timeout", "crash": "crash"}


def compute_delta_elo_report(wins, draws, losses, faults=None, penalties=None):
    """JSON-serializable Track B score report."""
    penalties = penalties or DEFAULT_PENALTIES
    faults = faults or {"illegal": 0, "timeout": 0, "crash": 0}
    games = wins + draws + losses
    report = {
        "schema": "ceb.score.track_b/v1",
        "wins": wins, "draws": draws, "losses": losses, "games": games,
        "faults": faults,
    }
    if games > 0:
        lo, mid, hi = elo.delta_elo_ci(wins, draws, losses)
        report["score_rate"] = round(
            elo.clamp_rate(elo.score_rate(wins, draws, losses), games), 4)
        report["delta_elo"] = round(mid, 1)
        report["delta_elo_ci95"] = [round(lo, 1), round(hi, 1)]
    else:
        report["score_rate"] = None
        report["delta_elo"] = None
        report["delta_elo_ci95"] = None
    penalty_total = sum(
        faults.get(kind, 0) * penalties.get(key, 0)
        for kind, key in _FAULT_TO_PENALTY_KEY.items()
    )
    report["penalty_points"] = penalty_total
    if report["delta_elo"] is not None:
        report["final_delta_elo"] = round(report["delta_elo"] - penalty_total, 1)
    else:
        report["final_delta_elo"] = None
    return report
