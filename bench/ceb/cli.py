"""ceb — chess_en_bench command-line interface.

    ceb doctor
    ceb workspace prepare --track A --run-id demo
    ceb gate run --track A --workspace <dir> [--strict] [--sandbox docker]
    ceb round run --track A --workspace <dir> --round 1 [--quick] [--sandbox docker]
    ceb leaderboard compute --track A --results runs [--include-quick]
    ceb server start --host 127.0.0.1 --port 8000
    ceb track-b status
    ceb track-b check-diff --baseline <dir> --candidate <dir>
    ceb track-b round run --candidate-engine <path> --baseline-engine <path>

Also runnable as `python -m ceb.cli`.
"""

import argparse
import importlib.util
import json
import platform
import shutil
import sys
from pathlib import Path

from ceb import __version__


def _print(msg=""):
    sys.stdout.write(str(msg) + "\n")


# ----- doctor -----------------------------------------------------------------

def cmd_doctor(args):
    from ceb import paths

    _print("chess_en_bench doctor (v%s)" % __version__)
    _print("  python      : %s (%s)" % (platform.python_version(), sys.executable))
    _print("  platform    : %s" % platform.platform())

    try:
        root = paths.find_repo_root()
        _print("  repo root   : %s" % root)
        for track in ("a_from_scratch", "b_stockfish_opt"):
            present = (root / "tracks" / track).is_dir()
            _print("  track %-13s: %s" % (track, "ok" if present else "MISSING"))
    except FileNotFoundError as exc:
        _print("  repo root   : NOT FOUND (%s)" % exc)

    _print("  optional python deps:")
    for mod, why in (("fastapi", "API server"), ("uvicorn", "API server"),
                     ("pytest", "tests")):
        found = importlib.util.find_spec(mod) is not None
        hint = "" if found else '  -> pip install -e ".[dev,server]"'
        _print("    %-9s: %s (%s)%s" % (mod, "ok" if found else "missing", why, hint))

    _print("  optional external tools:")
    for tool, why in (("stockfish", "Track B baseline engine"),
                      ("fastchess", "external match runner (optional)"),
                      ("cutechess-cli", "external match runner (optional)"),
                      ("docker", "sandboxing (recommended)"),
                      ("git", "version control")):
        path = shutil.which(tool)
        _print("    %-13s: %s (%s)" % (tool, path or "missing", why))
    _print("")
    _print("Core gate/match/scoring need only the Python standard library.")
    _print("Missing optional tools degrade gracefully; see `ceb track-b status`.")
    return 0


# ----- workspace ----------------------------------------------------------------

_WORKSPACE_README = """\
# {run_id} — Track {track} workspace

Put your submission here (see specs/submission_contract.md):
  workspace/engine      executable UCI engine (or build.sh that creates it)
  workspace/build.sh    optional build script, run by the gate

Iterate freely against the public gate (unlimited attempts):
  ceb gate run --track {track} --workspace {workspace}

When the gate passes, spend an official round (budget is limited):
  ceb round run --track {track} --workspace {workspace} --round 1
"""


def cmd_workspace_prepare(args):
    from ceb import paths
    from ceb.rounds.state import RunState

    root = paths.find_repo_root()
    runs_root = Path(args.runs_dir) if args.runs_dir else paths.runs_dir(root)
    run_dir = runs_root / args.run_id
    workspace = run_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    track_dir = paths.track_dir(args.track, root)
    prompt_src = track_dir / "prompt.md"
    if prompt_src.is_file():
        (run_dir / "instructions.md").write_text(
            prompt_src.read_text(encoding="utf-8"), encoding="utf-8")
    (workspace / "README.md").write_text(
        _WORKSPACE_README.format(run_id=args.run_id, track=args.track.upper(),
                                 workspace=workspace),
        encoding="utf-8")

    RunState.load_or_create(runs_root, args.run_id, track=args.track.upper(),
                            workspace=workspace)
    _print("prepared run %r" % args.run_id)
    _print("  workspace    : %s" % workspace)
    _print("  instructions : %s" % (run_dir / "instructions.md"))
    _print("  public data  : %s" % (track_dir / "public"))
    _print("  state        : %s" % RunState.path_for(runs_root, args.run_id))
    return 0


# ----- gate ---------------------------------------------------------------------

def cmd_gate_run(args):
    from ceb import paths
    from ceb.eval_pack import resolve_eval_pack, EvalPackError
    from ceb.gate.gate_runner import run_gate, save_gate_report

    root = paths.find_repo_root()
    if args.sandbox == "docker":
        from ceb.sandbox import run_gate_in_docker, SandboxError
        try:
            return run_gate_in_docker(root, args.workspace, track=args.track,
                                      strict=args.strict,
                                      no_match=args.no_match)
        except SandboxError as exc:
            _print("sandbox error: %s" % exc)
            return 2
    try:
        # Hidden eval packs apply only to strict checks unless requested.
        pack = resolve_eval_pack(root, private_dir=args.eval_pack,
                                 allow_env=args.strict)
    except EvalPackError as exc:
        _print("eval pack error: %s" % exc)
        return 2
    report = run_gate(args.workspace, track=args.track, root=root,
                      quick_match=not args.no_match, strict=args.strict,
                      eval_pack=pack)
    out_path = save_gate_report(report, args.json_out, root=root)
    _print(report.human_summary())
    _print("")
    _print("JSON report: %s" % out_path)
    return 0 if report.passed else 2


# ----- round --------------------------------------------------------------------

def cmd_round_run(args):
    from ceb.eval_pack import EvalPackError
    from ceb.rounds.feedback import feedback_to_text
    from ceb.rounds.round_runner import run_round, RoundError

    if args.sandbox == "docker":
        from ceb import paths
        from ceb.sandbox import run_round_in_docker, SandboxError
        if args.eval_pack:
            _print("--eval-pack is not supported with --sandbox docker in "
                   "v0.2; set CEB_PRIVATE_EVAL_DIR inside a custom image or "
                   "run with --sandbox none")
            return 2
        try:
            return run_round_in_docker(
                paths.find_repo_root(), args.workspace,
                round_number=args.round, track=args.track, quick=args.quick,
                run_id=args.run_id)
        except SandboxError as exc:
            _print("sandbox error: %s" % exc)
            return 2
    try:
        report, feedback, state = run_round(
            args.workspace, args.round, quick=args.quick, run_id=args.run_id,
            track=args.track, runs_root=args.runs_dir,
            eval_pack_dir=args.eval_pack,
            progress=lambda msg: _print("  " + msg))
    except (RoundError, EvalPackError) as exc:
        _print("round aborted: %s" % exc)
        return 2
    _print("")
    _print(feedback_to_text(feedback))
    _print("")
    _print("report.json  : runs/%s/round_%d/report.json"
           % (report["run_id"], report["round"]))
    _print("official budget: %d used / %d total (quick rounds are free)"
           % (state.budget_used, state.budget_total))
    return 0


# ----- leaderboard ----------------------------------------------------------------

def cmd_leaderboard_compute(args):
    from ceb.scoring.track_a import compute_leaderboard

    board = compute_leaderboard(args.results, track=args.track,
                                include_quick=args.include_quick)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(board, indent=2) + "\n",
                                       encoding="utf-8")
        _print("leaderboard JSON written to %s" % args.json_out)
    _print("Leaderboard — track %s" % board["track"])
    if args.include_quick:
        _print("  (diagnostic view: quick rounds INCLUDED — not an official ranking)")
    else:
        _print("  (official rounds only; --include-quick shows diagnostic quick rounds)")
    if not board["entries"]:
        _print("  (no scored runs under %s)" % args.results)
        return 0
    _print("  %-4s %-28s %-10s %s" % ("#", "run", "score", "best round"))
    for i, e in enumerate(board["entries"], 1):
        best = e["best_round"]
        best_str = ("round %s (%s)" % (best["round"], best["mode"])) if best else "-"
        _print("  %-4d %-28s %-10s %s"
               % (i, e["run_id"], e["score"] if e["score"] is not None else "-",
                  best_str))
    return 0


# ----- server ---------------------------------------------------------------------

def cmd_server_start(args):
    try:
        import uvicorn
        from ceb.api.main import app  # noqa: F401 - import validates extras
    except ImportError:
        _print("The API server needs the 'server' extras. Install them with:")
        _print("  python3 -m venv .venv")
        _print("  . .venv/bin/activate")
        _print('  pip install -e ".[server]"')
        return 2
    _print("serving chess_en_bench dashboard at http://%s:%d/" % (args.host, args.port))
    uvicorn.run("ceb.api.main:app", host=args.host, port=args.port,
                log_level="info")
    return 0


# ----- track-b ---------------------------------------------------------------------

def cmd_track_b_status(args):
    from ceb.track_b.stockfish import stockfish_status

    status = stockfish_status()
    lock = status["lock"]
    _print("Track B baseline status")
    _print("  pinned release : %s (tag %s, commit %s)"
           % (lock.get("release"), lock.get("tag"), lock.get("commit")))
    _print("  sources        : %s (%s)"
           % (status["stockfish_dir"],
              "present" if status["present"] else "absent"))
    if status["head_commit"]:
        _print("  HEAD commit    : %s (matches lock: %s)"
               % (status["head_commit"][:12], status["commit_matches_lock"]))
    for action in status["actions"]:
        _print("  -> %s" % action)
    return 0


def _engine_command(spec):
    """Resolve an engine spec: a benchmark opponent name or an executable path."""
    from ceb.match.opponents import STRATEGIES, opponent_command

    if spec in STRATEGIES:
        return opponent_command(spec)
    path = Path(spec).resolve()
    if not path.is_file():
        raise FileNotFoundError("engine not found: %s (pass an executable "
                                "path or one of: %s)"
                                % (spec, ", ".join(STRATEGIES)))
    return [str(path)]


def cmd_track_b_round_run(args):
    from ceb.track_b.round_runner import run_track_b_round, TrackBRoundError

    try:
        candidate_cmd = _engine_command(args.candidate_engine)
        baseline_cmd = _engine_command(args.baseline_engine)
        report, feedback = run_track_b_round(
            candidate_cmd, baseline_cmd,
            round_number=args.round, run_id=args.run_id, games=args.games,
            movetime_ms=args.movetime, max_plies=args.max_plies,
            baseline_src=args.baseline_src, candidate_src=args.candidate_src,
            eval_pack_dir=args.eval_pack, runs_root=args.runs_dir,
            openings_limit=args.openings_limit,
            progress=lambda msg: _print("  " + msg))
    except (TrackBRoundError, FileNotFoundError) as exc:
        _print("track B round aborted: %s" % exc)
        return 2
    _print("")
    _print("Track B round %d — candidate vs baseline" % report["round"])
    totals = report["totals"]
    _print("  W%d D%d L%d over %d games" % (totals["wins"], totals["draws"],
                                            totals["losses"], feedback["games"]))
    _print("  delta Elo: %s  (95%% CI %s)  final after penalties: %s"
           % (feedback["delta_elo"], feedback["delta_elo_ci95"],
              feedback["final_delta_elo"]))
    _print("  report: runs/%s/track_b_round_%d/report.json"
           % (report["run_id"], report["round"]))
    return 0


def cmd_track_b_check_diff(args):
    from ceb import paths
    from ceb.track_b.diff_policy import check_diff, load_patterns

    track_dir = paths.track_dir("B")
    allowed = load_patterns(args.allowed or track_dir / "allowed_paths.txt")
    forbidden = load_patterns(args.forbidden or track_dir / "forbidden_paths.txt")
    report = check_diff(args.baseline, args.candidate, allowed, forbidden)
    _print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 2


# ----- parser ----------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="ceb",
        description="chess_en_bench: benchmark for LLM agents that build or "
                    "optimize chess engines")
    parser.add_argument("--version", action="version",
                        version="chess_en_bench %s" % __version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("doctor", help="diagnose environment and dependencies")
    p.set_defaults(func=cmd_doctor)

    ws = sub.add_parser("workspace", help="manage run workspaces")
    ws_sub = ws.add_subparsers(dest="subcommand", required=True)
    p = ws_sub.add_parser("prepare", help="create a run workspace skeleton")
    p.add_argument("--track", default="A")
    p.add_argument("--run-id", required=True)
    p.add_argument("--runs-dir", default=None, help="override runs/ root (tests)")
    p.set_defaults(func=cmd_workspace_prepare)

    gate = sub.add_parser("gate", help="public correctness gate")
    gate_sub = gate.add_subparsers(dest="subcommand", required=True)
    p = gate_sub.add_parser("run", help="run the gate on a workspace")
    p.add_argument("--track", default="A")
    p.add_argument("--workspace", required=True)
    p.add_argument("--json-out", default=None)
    p.add_argument("--no-match", action="store_true",
                   help="skip the mini match smoke check")
    p.add_argument("--strict", action="store_true",
                   help="official-round policy: 'go perft' is mandatory")
    p.add_argument("--sandbox", choices=["none", "docker"], default="none",
                   help="run inside the Docker evaluator sandbox "
                        "(recommended for untrusted submissions)")
    p.add_argument("--eval-pack", default=None,
                   help="private eval pack directory (operator only)")
    p.set_defaults(func=cmd_gate_run)

    rnd = sub.add_parser("round", help="official/quick evaluation rounds")
    rnd_sub = rnd.add_subparsers(dest="subcommand", required=True)
    p = rnd_sub.add_parser("run", help="run one round (gate must pass)")
    p.add_argument("--track", default="A")
    p.add_argument("--workspace", required=True)
    p.add_argument("--round", type=int, required=True)
    p.add_argument("--quick", action="store_true",
                   help="reduced match set; does not consume official budget")
    p.add_argument("--run-id", default=None)
    p.add_argument("--runs-dir", default=None, help="override runs/ root (tests)")
    p.add_argument("--sandbox", choices=["none", "docker"], default="none",
                   help="run inside the Docker evaluator sandbox "
                        "(recommended for untrusted submissions)")
    p.add_argument("--eval-pack", default=None,
                   help="private eval pack directory (operator only)")
    p.set_defaults(func=cmd_round_run)

    lb = sub.add_parser("leaderboard", help="aggregate run scores")
    lb_sub = lb.add_subparsers(dest="subcommand", required=True)
    p = lb_sub.add_parser("compute", help="rank runs by best valid round")
    p.add_argument("--track", default="A")
    p.add_argument("--results", default="runs", help="runs directory to scan")
    p.add_argument("--json-out", default=None)
    p.add_argument("--include-quick", action="store_true",
                   help="diagnostic only: also rank quick rounds")
    p.set_defaults(func=cmd_leaderboard_compute)

    srv = sub.add_parser("server", help="API server + dashboard")
    srv_sub = srv.add_subparsers(dest="subcommand", required=True)
    p = srv_sub.add_parser("start", help="start the FastAPI server")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_server_start)

    tb = sub.add_parser("track-b", help="Stockfish optimization track tools")
    tb_sub = tb.add_subparsers(dest="subcommand", required=True)
    p = tb_sub.add_parser("status", help="pinned baseline / setup status")
    p.set_defaults(func=cmd_track_b_status)
    p = tb_sub.add_parser("check-diff", help="diff whitelist check")
    p.add_argument("--baseline", required=True)
    p.add_argument("--candidate", required=True)
    p.add_argument("--allowed", default=None)
    p.add_argument("--forbidden", default=None)
    p.set_defaults(func=cmd_track_b_check_diff)

    tb_round = tb_sub.add_parser("round", help="candidate-vs-baseline rounds")
    tb_round_sub = tb_round.add_subparsers(dest="subsubcommand", required=True)
    p = tb_round_sub.add_parser(
        "run", help="play candidate vs baseline and score delta Elo")
    p.add_argument("--candidate-engine", required=True,
                   help="executable path or a benchmark opponent name")
    p.add_argument("--baseline-engine", required=True,
                   help="executable path or a benchmark opponent name")
    p.add_argument("--baseline-src", default=None,
                   help="baseline source tree for the diff whitelist check")
    p.add_argument("--candidate-src", default=None,
                   help="candidate source tree for the diff whitelist check")
    p.add_argument("--round", type=int, default=1)
    p.add_argument("--run-id", default="track_b_local")
    p.add_argument("--games", type=int, default=8)
    p.add_argument("--movetime", type=int, default=100)
    p.add_argument("--max-plies", type=int, default=300)
    p.add_argument("--openings-limit", type=int, default=None)
    p.add_argument("--eval-pack", default=None)
    p.add_argument("--runs-dir", default=None, help="override runs/ root (tests)")
    p.set_defaults(func=cmd_track_b_round_run)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        _print("interrupted")
        return 130
    except FileNotFoundError as exc:
        _print("error: %s" % exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
