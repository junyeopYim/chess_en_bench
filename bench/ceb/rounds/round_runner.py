"""Round execution: gate precondition, budget accounting, matches, scoring."""

import json
import time
from pathlib import Path

from ceb import paths
from ceb.config import load_scoring_config, load_track_config
from ceb.gate.gate_runner import run_gate, save_gate_report
from ceb.match.internal_runner import play_match
from ceb.match.opponents import opponent_command
from ceb.rounds.feedback import make_feedback
from ceb.rounds.state import RunState
from ceb.scoring.track_a import (
    compute_round_score, DEFAULT_OPPONENT_RATINGS, DEFAULT_PENALTIES,
)

DEFAULT_ROUND_MODES = {
    "quick": {
        "opponents": ["BenchRandom", "BenchMaterial1"],
        "games_per_opponent": 2,
        "movetime_ms": 50,
        "max_plies": 120,
    },
    "official": {
        "opponents": ["BenchRandom", "BenchGreedyCapture", "BenchMaterial1",
                      "BenchPST1", "BenchMiniMax2", "BenchAlphaBeta3"],
        "games_per_opponent": 4,
        "movetime_ms": 200,
        "max_plies": 200,
    },
}


class RoundError(Exception):
    """Round could not start or complete; message is user-facing."""


def _scoring_config(root):
    try:
        return load_scoring_config("A", root) or {}
    except (FileNotFoundError, ValueError):
        return {}


def _round_mode_config(scoring_cfg, mode):
    modes = scoring_cfg.get("round_modes") or {}
    cfg = dict(DEFAULT_ROUND_MODES[mode])
    cfg.update({k: v for k, v in (modes.get(mode) or {}).items() if v is not None})
    return cfg


def _budget_total(root):
    try:
        track_cfg = load_track_config("A", root) or {}
        return int(track_cfg.get("official_rounds", 3))
    except (FileNotFoundError, ValueError, TypeError):
        return 3


def default_run_id(workspace):
    return Path(workspace).resolve().name


def run_round(workspace, round_number, *, quick=False, run_id=None, track="A",
              root=None, runs_root=None, progress=lambda msg: None):
    """Run one round. Returns (round_report dict, feedback dict, state).

    Raises RoundError when preconditions fail (gate, budget).
    """
    if root is None:
        root = paths.find_repo_root()
    runs_root = Path(runs_root) if runs_root else paths.runs_dir(root)
    workspace = Path(workspace).resolve()
    if run_id is None:
        run_id = default_run_id(workspace)
    mode = "quick" if quick else "official"

    state = RunState.load_or_create(runs_root, run_id, track="A",
                                    workspace=workspace,
                                    budget_total=_budget_total(root))

    # Gate precondition: re-run now so the round always starts from a
    # verified engine (gate attempts are unlimited).
    progress("running public gate on %s ..." % workspace)
    gate_report = run_gate(workspace, track="A", root=root)
    gate_path = save_gate_report(
        gate_report, runs_root / run_id / "gate_report.json")
    state.record_gate(gate_report.passed, gate_path)
    state.save(runs_root)
    if not gate_report.passed:
        raise RoundError("gate failed; round not started.\n\n"
                         + gate_report.human_summary())

    ok, why = state.can_start_round(official=(mode == "official"))
    if not ok:
        raise RoundError(why)

    scoring_cfg = _scoring_config(root)
    mode_cfg = _round_mode_config(scoring_cfg, mode)
    opponent_ratings = scoring_cfg.get("opponent_ratings") or DEFAULT_OPPONENT_RATINGS
    penalties = scoring_cfg.get("penalties") or DEFAULT_PENALTIES

    round_dir = runs_root / run_id / ("round_%d" % round_number)
    round_dir.mkdir(parents=True, exist_ok=True)

    engine_cmd = [str(workspace / "engine")]
    match_reports = []
    for opponent in mode_cfg["opponents"]:
        progress("match vs %s (%d games, movetime %dms) ..."
                 % (opponent, mode_cfg["games_per_opponent"], mode_cfg["movetime_ms"]))
        report = play_match(
            engine_cmd, opponent_command(opponent),
            games=int(mode_cfg["games_per_opponent"]),
            movetime_ms=int(mode_cfg["movetime_ms"]),
            max_plies=int(mode_cfg["max_plies"]),
            candidate_name=run_id,
            opponent_name=opponent,
            candidate_cwd=str(workspace),
            base_seed=1000 * round_number,
            games_text_path=round_dir / ("games_vs_%s.txt" % opponent),
        )
        match_reports.append(report)
        (round_dir / ("match_vs_%s.json" % opponent)).write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8")

    score = compute_round_score(match_reports, opponent_ratings, penalties)
    round_report = {
        "schema": "ceb.round.report/v1",
        "run_id": run_id,
        "track": "A",
        "round": round_number,
        "mode": mode,
        "workspace": str(workspace),
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "matches": [
            {"opponent": r["opponent"], "totals": r["totals"],
             "candidate_faults": r["candidate_faults"]}
            for r in match_reports
        ],
        "score": score,
    }
    report_path = round_dir / "report.json"
    report_path.write_text(json.dumps(round_report, indent=2) + "\n",
                           encoding="utf-8")

    state.record_round(round_number, mode, report_path, score["final_score"])
    state.save(runs_root)

    feedback = make_feedback(round_report)
    (round_dir / "feedback.json").write_text(
        json.dumps(feedback, indent=2) + "\n", encoding="utf-8")
    return round_report, feedback, state
