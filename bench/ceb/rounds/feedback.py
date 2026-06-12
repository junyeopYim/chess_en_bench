"""Sanitized round feedback.

Feedback is aggregate-only by design: per-opponent W/D/L and score rates,
fault counts, and the round score. It never includes opponent move logs,
private positions, or anything beyond the public data the agent already has,
so agents can iterate without leaking evaluation internals.
"""


def make_feedback(round_report):
    """Build the sanitized feedback dict from a full round report."""
    score = round_report["score"]
    per_opponent = [
        {
            "opponent": e["opponent"],
            "games": e["games"],
            "wins": e["wins"],
            "draws": e["draws"],
            "losses": e["losses"],
            "score_rate": e["score_rate"],
        }
        for e in score["per_opponent"]
    ]
    advice = []
    faults = score["faults"]
    if faults.get("illegal"):
        advice.append("Illegal moves detected: re-check move legality "
                      "(castling rights, en passant, pins) against the public "
                      "perft data before the next round.")
    if faults.get("timeout"):
        advice.append("Timeouts detected: respect 'go movetime' and always "
                      "answer with a bestmove line.")
    if faults.get("crash"):
        advice.append("Crashes detected: the engine process exited mid-game; "
                      "harden input parsing and avoid unhandled exceptions.")
    if not advice:
        advice.append("No protocol faults. Improving search depth and "
                      "evaluation is the main lever for a higher ladder score.")
    return {
        "schema": "ceb.round.feedback/v1",
        "round": round_report["round"],
        "mode": round_report["mode"],
        "per_opponent": per_opponent,
        "overall": score.get("overall"),
        "opening_coverage": score.get("opening_coverage"),
        "faults": faults,
        "penalty_points": score["penalty_points"],
        "ladder_score": score["ladder_score"],
        "final_score": score["final_score"],
        "advice": advice,
    }


def feedback_to_text(feedback):
    lines = [
        "Round %s feedback (%s mode)" % (feedback["round"], feedback["mode"]),
        "",
    ]
    for e in feedback["per_opponent"]:
        rate = "%.0f%%" % (100 * e["score_rate"]) if e["score_rate"] is not None else "n/a"
        lines.append("  vs %-20s W%d D%d L%d  (score rate %s)"
                     % (e["opponent"], e["wins"], e["draws"], e["losses"], rate))
    lines.append("")
    lines.append("  faults: %s   penalty: -%s"
                 % (feedback["faults"], feedback["penalty_points"]))
    lines.append("  ladder score: %s   final score: %s"
                 % (feedback["ladder_score"], feedback["final_score"]))
    lines.append("")
    for tip in feedback["advice"]:
        lines.append("  hint: %s" % tip)
    return "\n".join(lines)
