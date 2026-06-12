"""Round execution: gate precondition, budget accounting, matches, scoring.

Eval modes:
  quick             tiny, free, diagnostic; non-strict gate
  official_round    consumes one unit of the official round budget; strict gate
  final_eval        leaderboard-quality evaluation; strict gate; does not
                    consume round budget (hosted policy decides when it runs)
  final_production  production-scale final eval (thousands of games, paired
                    openings) for a public leaderboard CI; strict gate; no
                    budget cost; configured in eval_profiles.yaml

Official-grade modes draw start positions from the resolved eval pack
(public + optional operator-mounted hidden pack) and rotate openings across
opponents. The untrusted engine can be confined with engine_jail="docker";
the eval pack is read by the evaluator only and is never mounted into the
jail. Artifacts are written with an explicit visibility model: feedback and
the public report are sanitized; full reports, match logs, and game text are
private operator artifacts.
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
from ceb.storage import (
    VISIBILITY_PRIVATE, VISIBILITY_PUBLIC, register_artifact, write_artifact,
)

MODE_QUICK = "quick"
MODE_OFFICIAL = "official_round"
MODE_FINAL = "final_eval"
# final_production: leaderboard-quality production evaluation. Substantially
# larger than final_eval (thousands of games, paired openings) so the
# delta-Elo confidence interval is tight enough for a public ranking. NEVER
# run by CI/tests with its configured defaults — tests pass a tiny
# mode_config override. See tracks/a_from_scratch/eval_profiles.yaml.
MODE_FINAL_PRODUCTION = "final_production"
EVAL_MODES = (MODE_QUICK, MODE_OFFICIAL, MODE_FINAL, MODE_FINAL_PRODUCTION)

# Modes that consume one unit of the official round budget.
_BUDGET_MODES = {MODE_OFFICIAL}
# Final-tier modes (leaderboard prefers these over official rounds).
FINAL_MODES = (MODE_FINAL, MODE_FINAL_PRODUCTION)
# Legacy v0.2 records used "official" for official rounds.
LEGACY_OFFICIAL = "official"

DEFAULT_ROUND_MODES = {
    MODE_QUICK: {
        "opponents": ["BenchRandom", "BenchMaterial1"],
        "games_per_opponent": 2,
        "movetime_ms": 50,
        "max_plies": 120,
        "openings_limit": 2,
    },
    MODE_OFFICIAL: {
        "opponents": ["BenchRandom", "BenchGreedyCapture", "BenchMaterial1",
                      "BenchPST1", "BenchMiniMax2", "BenchAlphaBeta3"],
        "games_per_opponent": 4,
        "movetime_ms": 200,
        "max_plies": 200,
        "openings_limit": 6,
    },
    MODE_FINAL: {
        "opponents": ["BenchRandom", "BenchGreedyCapture", "BenchMaterial1",
                      "BenchPST1", "BenchMiniMax2", "BenchAlphaBeta3"],
        "games_per_opponent": 8,
        "movetime_ms": 200,
        "max_plies": 200,
        "openings_limit": 8,
    },
    # Production final eval. 6 opponents x 336 games = 2016 games total, with
    # paired openings (the internal runner alternates colours per pair). These
    # defaults are the floor for a credible leaderboard CI; operators raise
    # them via tracks/a_from_scratch/eval_profiles.yaml. Do NOT run in CI.
    MODE_FINAL_PRODUCTION: {
        "opponents": ["BenchRandom", "BenchGreedyCapture", "BenchMaterial1",
                      "BenchPST1", "BenchMiniMax2", "BenchAlphaBeta3"],
        "games_per_opponent": 336,
        "movetime_ms": 1000,
        "max_plies": 300,
        "openings_limit": 24,
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
    loaded = modes.get(mode)
    if loaded is None and mode == MODE_OFFICIAL:
        loaded = modes.get(LEGACY_OFFICIAL)  # legacy config key
    cfg.update({k: v for k, v in (loaded or {}).items() if v is not None})
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

    Anchors degrade gracefully by default: a missing engine binary skips the
    anchor with a progress note. With mode_cfg["anchors_required"] truthy
    (hosted official config), a missing anchor aborts the round instead.
    """
    specs = [{"name": name, "cmd": opponent_command(name), "options": None}
             for name in mode_cfg["opponents"]]
    anchor_cfg = scoring_cfg.get("anchor_opponents") or {}
    required = bool(mode_cfg.get("anchors_required"))
    for name in mode_cfg.get("anchors") or []:
        spec = anchor_cfg.get(name)
        if not isinstance(spec, dict):
            if required:
                raise RoundError("required anchor %s is not defined in "
                                 "scoring.yaml anchor_opponents" % name)
            progress("skipping anchor %s: not defined in scoring.yaml "
                     "anchor_opponents" % name)
            continue
        engine = shutil.which(str(spec.get("engine", "stockfish")))
        if not engine:
            if required:
                raise RoundError("required anchor %s: engine %r not on PATH"
                                 % (name, spec.get("engine", "stockfish")))
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


def make_public_report(round_report, pack):
    """Sanitized, agent/public-safe view of a round report.

    Excludes host paths, hidden opening ids, per-game data, and anything
    derived from private pack contents beyond counts.
    """
    pack_is_private = pack.source != "public"
    openings_used = round_report.get("openings_used", [])
    public = {
        "schema": "ceb.round.report.public/v1",
        "run_id": round_report["run_id"],
        "track": round_report["track"],
        "round": round_report["round"],
        "mode": round_report["mode"],
        "strict_gate": round_report["strict_gate"],
        "finished_at": round_report["finished_at"],
        "eval_pack": {
            "name": pack.name,
            "source": pack.source,
        },
        "opening_coverage": {
            "openings_played": len(openings_used),
            # Opening ids are public only for fully-public packs.
            "opening_ids": openings_used if not pack_is_private else None,
        },
        "matches": round_report["matches"],
        "score": round_report["score"],
        "verified": False,  # local results are self-reported / diagnostic
    }
    return public


def run_round(workspace, round_number, *, quick=False, mode=None, run_id=None,
              track="A", root=None, runs_root=None, eval_pack_dir=None,
              mode_config=None, engine_jail="none", stage_public=False,
              progress=lambda msg: None):
    """Run one round. Returns (round_report dict, feedback dict, state).

    mode: one of quick / official_round / final_eval (quick=True is a
    shorthand for mode="quick"; the default is official_round).
    Official-grade modes use the strict gate and may consume an
    operator-mounted hidden eval pack (--eval-pack / CEB_PRIVATE_EVAL_DIR);
    quick rounds are non-strict and use public data unless eval_pack_dir is
    passed explicitly. mode_config overrides the configured round mode
    (operator/testing knob). engine_jail confines the untrusted engine.

    Raises RoundError when preconditions fail (gate, budget).
    """
    if root is None:
        root = paths.find_repo_root()
    runs_root = Path(runs_root) if runs_root else paths.runs_dir(root)
    workspace = Path(workspace).resolve()
    if run_id is None:
        run_id = default_run_id(workspace)
    if mode is None:
        mode = MODE_QUICK if quick else MODE_OFFICIAL
    if mode not in EVAL_MODES:
        raise RoundError("unknown eval mode %r (use one of: %s)"
                         % (mode, ", ".join(EVAL_MODES)))
    strict = mode != MODE_QUICK

    pack = resolve_eval_pack(root, private_dir=eval_pack_dir, allow_env=strict)

    state = RunState.load_or_create(runs_root, run_id, track="A",
                                    workspace=workspace,
                                    budget_total=_budget_total(root))

    # Gate precondition: re-run now so the round always starts from a
    # verified engine (gate attempts are unlimited). Official-grade modes
    # use the strict gate: 'go perft' support is mandatory.
    progress("running %s gate on %s ..." % ("strict" if strict else "public",
                                            workspace))
    gate_report = run_gate(workspace, track="A", root=root, strict=strict,
                           eval_pack=pack, engine_jail=engine_jail)
    gate_path = save_gate_report(
        gate_report, runs_root / run_id / "gate_report.json")
    state.record_gate(gate_report.passed, gate_path)
    state.save(runs_root)
    if not gate_report.passed:
        raise RoundError("%s gate failed; round not started and no budget "
                         "spent.\n\n%s" % ("strict" if strict else "public",
                                           gate_report.human_summary()))

    ok, why = state.can_start_round(official=(mode in _BUDGET_MODES))
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

    from ceb.jail import engine_command, cleanup_jails
    engine_cmd, engine_cwd = engine_command(workspace, engine_jail)
    games = int(mode_cfg["games_per_opponent"])
    pairs = max(1, (games + 1) // 2)
    match_reports = []
    try:
        for j, opponent in enumerate(opponents):
            # Rotate the suite so the round as a whole covers more openings
            # than any single match plays.
            openings = rotate_suite(suite, pairs, (j * pairs) % len(suite))
            progress("match vs %s (%d games, movetime %dms, %d opening(s)) ..."
                     % (opponent["name"], games, mode_cfg["movetime_ms"],
                        len(openings)))
            report = play_match(
                engine_cmd, opponent["cmd"],
                games=games,
                movetime_ms=int(mode_cfg["movetime_ms"]),
                max_plies=int(mode_cfg["max_plies"]),
                candidate_name=run_id,
                opponent_name=opponent["name"],
                candidate_cwd=engine_cwd,
                base_seed=1000 * round_number,
                games_text_path=round_dir / ("games_vs_%s.txt" % opponent["name"]),
                openings=openings,
                opponent_uci_options=opponent["options"],
            )
            match_reports.append(report)
            write_artifact(round_dir, "match_vs_%s.json" % opponent["name"],
                           report, VISIBILITY_PRIVATE)
            register_artifact(round_dir, "games_vs_%s.txt" % opponent["name"],
                              VISIBILITY_PRIVATE)
    finally:
        if engine_jail != "none":
            cleanup_jails()

    score = compute_round_score(match_reports, opponent_ratings, penalties)
    openings_used = sorted({o for r in match_reports for o in r.get("openings", [])})
    score["opening_coverage"] = {
        "openings_played": len(openings_used),
        "suite_size": len(suite),
    }
    round_report = {
        "schema": "ceb.round.report/v1",
        "run_id": run_id,
        "track": "A",
        "round": round_number,
        "mode": mode,
        "strict_gate": strict,
        "engine_jail": engine_jail,
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
    # Full report (host paths, hidden opening ids) is a private artifact;
    # report.public.json and feedback.json are the sanitized views. In the
    # hosted official flow (stage_public=True) the sanitized views are written
    # STAGED (private until leak-scanned + promoted); local diagnostic rounds
    # write them public directly.
    write_artifact(round_dir, "report.json", round_report, VISIBILITY_PRIVATE)
    register_artifact(runs_root / run_id, "gate_report.json", VISIBILITY_PRIVATE)
    feedback = make_feedback(round_report)
    public_report = make_public_report(round_report, pack)
    if stage_public:
        from ceb.storage.promotion import write_staged_public_artifact
        write_staged_public_artifact(round_dir, "report.public.json", public_report)
        write_staged_public_artifact(round_dir, "feedback.json", feedback)
    else:
        write_artifact(round_dir, "report.public.json", public_report,
                       VISIBILITY_PUBLIC)
        write_artifact(round_dir, "feedback.json", feedback, VISIBILITY_PUBLIC)

    state.record_round(round_number, mode, round_dir / "report.json",
                       score["final_score"])
    state.save(runs_root)
    return round_report, feedback, state
