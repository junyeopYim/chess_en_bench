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

    # Overall aggregate with a 95% CI on the pooled score rate (vs a mixed
    # opponent pool, so the Elo CI is indicative, not a single-opponent
    # rating).
    total_w = sum(e["wins"] for e in per_opponent)
    total_d = sum(e["draws"] for e in per_opponent)
    total_l = sum(e["losses"] for e in per_opponent)
    total_games = total_w + total_d + total_l
    overall = {
        "games": total_games,
        "wins": total_w, "draws": total_d, "losses": total_l,
        "score_rate": None,
        "delta_elo_vs_pool": None,
        "delta_elo_ci95": None,
    }
    if total_games > 0:
        lo, mid, hi = elo.delta_elo_ci(total_w, total_d, total_l)
        overall["score_rate"] = round(
            elo.clamp_rate(elo.score_rate(total_w, total_d, total_l),
                           total_games), 4)
        overall["delta_elo_vs_pool"] = round(mid, 1)
        overall["delta_elo_ci95"] = [round(lo, 1), round(hi, 1)]

    return {
        "schema": "ceb.score.track_a/v1",
        "per_opponent": per_opponent,
        "overall": overall,
        "faults": fault_totals,
        "penalty_points": penalty_total,
        "ladder_score": round(ladder, 1) if ladder is not None else None,
        "final_score": final,
    }


# Mode classification for leaderboard eligibility. "official" is the legacy
# v0.2 record name for official rounds. final_production is the production
# leaderboard mode; both final modes outrank official rounds.
OFFICIAL_MODES = {"official", "official_round"}
FINAL_MODES = {"final_eval", "final_production"}


def compute_leaderboard(results_dir, track="A", include_quick=False):
    """Scan runs/*/state.json + round reports and rank runs.

    Selection per run: the best final_eval result if any exists, otherwise
    the best official round. Quick rounds NEVER count unless
    include_quick=True (a diagnostic view, never an official ranking).
    Entries from this scanner are self-reported: verified is always false —
    verified results come only from the hosted worker (ceb hosted ...).

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
            best_official = None
            best_final = None
            best_quick = None
            for rnd in rounds:
                score = rnd.get("score")
                mode = rnd.get("mode", "official")
                if score is None:
                    continue
                slot = {"round": rnd.get("round"), "score": score, "mode": mode}
                if mode in FINAL_MODES:
                    if best_final is None or score > best_final["score"]:
                        best_final = slot
                elif mode in OFFICIAL_MODES:
                    if best_official is None or score > best_official["score"]:
                        best_official = slot
                elif include_quick:
                    if best_quick is None or score > best_quick["score"]:
                        best_quick = slot
            if include_quick:
                # Diagnostic view: best score across every mode.
                candidates = [c for c in (best_final, best_official, best_quick)
                              if c is not None]
                best = max(candidates, key=lambda c: c["score"]) if candidates else None
            else:
                # Official policy: final eval beats official rounds; quick
                # rounds never count.
                best = best_final or best_official
            entries.append({
                "run_id": state.get("run_id", state_path.parent.name),
                "workspace": state.get("workspace"),
                "gate_passed": bool(state.get("gate", {}).get("passed")),
                "rounds_played": len(rounds),
                "official_rounds_played": sum(
                    1 for r in rounds
                    if r.get("mode", "official") in OFFICIAL_MODES | FINAL_MODES),
                "best_round": best,
                "score": best["score"] if best else None,
                "verified": False,  # self-reported; hosted worker results only
            })
    entries.sort(key=lambda e: (e["score"] is None, -(e["score"] or 0)))
    return {"schema": "ceb.leaderboard/v1", "track": track.upper(),
            "include_quick": include_quick, "verified_only": False,
            "entries": entries}
