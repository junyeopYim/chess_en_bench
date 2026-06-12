"""Round execution: gate precondition, budget accounting, matches, scoring.

v0.2 policy: official rounds run the STRICT gate (perft required), draw
their start positions from the opening suite of the resolved eval pack
(public + optional operator-mounted hidden pack), and rotate openings
across opponents so a round covers the whole suite. Quick rounds stay
non-strict, free, and use a small public opening subset.
"""

import json
import shutil
import time
from pathlib import Path

from ceb import paths
from ceb.config import load_scoring_config, load_track_config
from ceb.eval_pack import resolve_eval_pack
from ceb.gate.gate_runner import run_gate, save_gate_report
from ceb.match.internal_runner import play_match
from ceb.match.openings import rotate_suite
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
        "openings_limit": 2,
    },
    "official": {
        "opponents": ["BenchRandom", "BenchGreedyCapture", "BenchMaterial1",
                      "BenchPST1", "BenchMiniMax2", "BenchAlphaBeta3"],
        "games_per_opponent": 4,
        "movetime_ms": 200,
        "max_plies": 200,
        "openings_limit": 6,
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
    """Infer a run id from a workspace path.

    Prepared workspaces live at runs/<run_id>/workspace; in that layout the
    parent directory (which holds state.json) names the run. Otherwise the
    workspace directory name is used. An explicit --run-id always overrides
    this inference.
    """
    workspace = Path(workspace).resolve()
    if workspace.name == "workspace" and (workspace.parent / "state.json").is_file():
        return workspace.parent.name
    return workspace.name


def _resolve_opponents(mode_cfg, scoring_cfg, progress):
    """Opponent specs for a round: the benchmark pool plus optional
    limited-strength anchor engines (e.g. Stockfish UCI_Elo levels).

    Anchors degrade gracefully: a missing engine binary skips the anchor
    with a progress note instead of failing the round.
    """
    specs = [{"name": name, "cmd": opponent_command(name), "options": None}
             for name in mode_cfg["opponents"]]
    anchor_cfg = scoring_cfg.get("anchor_opponents") or {}
    for name in mode_cfg.get("anchors") or []:
        spec = anchor_cfg.get(name)
        if not isinstance(spec, dict):
            progress("skipping anchor %s: not defined in scoring.yaml "
                     "anchor_opponents" % name)
            continue
        engine = shutil.which(str(spec.get("engine", "stockfish")))
        if not engine:
            progress("skipping anchor %s: engine %r not on PATH"
                     % (name, spec.get("engine", "stockfish")))
            continue
        specs.append({
            "name": name,
            "cmd": [engine],
            "options": {"UCI_LimitStrength": "true",
                        "UCI_Elo": spec.get("uci_elo", 1320),
                        "Threads": "1"},
        })
    return specs


def _openings_for_mode(pack, mode_cfg):
    """The opening subset a round mode draws from."""
    suite = pack.openings
    limit = mode_cfg.get("openings_limit")
    if limit:
        suite = suite[:int(limit)]
    if not suite:
        raise RoundError("the resolved eval pack has no openings")
    return suite


def run_round(workspace, round_number, *, quick=False, run_id=None, track="A",
              root=None, runs_root=None, eval_pack_dir=None, mode_config=None,
              progress=lambda msg: None):
    """Run one round. Returns (round_report dict, feedback dict, state).

    Official rounds use the strict gate and may consume an operator-mounted
    hidden eval pack (--eval-pack / CEB_PRIVATE_EVAL_DIR); quick rounds are
    non-strict and use public data unless eval_pack_dir is passed explicitly.
    mode_config overrides the configured round mode (operator/testing knob).

    Raises RoundError when preconditions fail (gate, budget).
    """
    if root is None:
        root = paths.find_repo_root()
    runs_root = Path(runs_root) if runs_root else paths.runs_dir(root)
    workspace = Path(workspace).resolve()
    if run_id is None:
        run_id = default_run_id(workspace)
    mode = "quick" if quick else "official"
    strict = mode == "official"

    pack = resolve_eval_pack(root, private_dir=eval_pack_dir, allow_env=strict)

    state = RunState.load_or_create(runs_root, run_id, track="A",
                                    workspace=workspace,
                                    budget_total=_budget_total(root))

    # Gate precondition: re-run now so the round always starts from a
    # verified engine (gate attempts are unlimited). Official rounds use
    # the strict gate: 'go perft' support is mandatory.
    progress("running %s gate on %s ..." % ("strict" if strict else "public",
                                            workspace))
    gate_report = run_gate(workspace, track="A", root=root, strict=strict,
                           eval_pack=pack)
    gate_path = save_gate_report(
        gate_report, runs_root / run_id / "gate_report.json")
    state.record_gate(gate_report.passed, gate_path)
    state.save(runs_root)
    if not gate_report.passed:
        raise RoundError("%s gate failed; round not started and no budget "
                         "spent.\n\n%s" % ("strict" if strict else "public",
                                           gate_report.human_summary()))

    ok, why = state.can_start_round(official=(mode == "official"))
    if not ok:
        raise RoundError(why)

    scoring_cfg = _scoring_config(root)
    mode_cfg = _round_mode_config(scoring_cfg, mode)
    if mode_config:
        mode_cfg.update(mode_config)
    opponent_ratings = dict(scoring_cfg.get("opponent_ratings")
                            or DEFAULT_OPPONENT_RATINGS)
    for name, spec in (scoring_cfg.get("anchor_opponents") or {}).items():
        if isinstance(spec, dict) and "rating" in spec:
            opponent_ratings.setdefault(name, spec["rating"])
    penalties = scoring_cfg.get("penalties") or DEFAULT_PENALTIES
    suite = _openings_for_mode(pack, mode_cfg)
    opponents = _resolve_opponents(mode_cfg, scoring_cfg, progress)

    round_dir = runs_root / run_id / ("round_%d" % round_number)
    round_dir.mkdir(parents=True, exist_ok=True)

    engine_cmd = [str(workspace / "engine")]
    games = int(mode_cfg["games_per_opponent"])
    pairs = max(1, (games + 1) // 2)
    match_reports = []
    for j, opponent in enumerate(opponents):
        # Rotate the suite so the round as a whole covers more openings
        # than any single match plays.
        openings = rotate_suite(suite, pairs, (j * pairs) % len(suite))
        progress("match vs %s (%d games, movetime %dms, openings %s) ..."
                 % (opponent["name"], games, mode_cfg["movetime_ms"],
                    ",".join(o["id"] for o in openings)))
        report = play_match(
            engine_cmd, opponent["cmd"],
            games=games,
            movetime_ms=int(mode_cfg["movetime_ms"]),
            max_plies=int(mode_cfg["max_plies"]),
            candidate_name=run_id,
            opponent_name=opponent["name"],
            candidate_cwd=str(workspace),
            base_seed=1000 * round_number,
            games_text_path=round_dir / ("games_vs_%s.txt" % opponent["name"]),
            openings=openings,
            opponent_uci_options=opponent["options"],
        )
        match_reports.append(report)
        (round_dir / ("match_vs_%s.json" % opponent["name"])).write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8")

    score = compute_round_score(match_reports, opponent_ratings, penalties)
    openings_used = sorted({o for r in match_reports for o in r.get("openings", [])})
    round_report = {
        "schema": "ceb.round.report/v1",
        "run_id": run_id,
        "track": "A",
        "round": round_number,
        "mode": mode,
        "strict_gate": strict,
        "eval_pack": pack.describe(),
        "openings_used": openings_used,
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
