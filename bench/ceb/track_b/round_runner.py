"""Track B automated round: candidate vs pinned-baseline evaluation.

Flow (ceb track-b round run):
  1. optional diff whitelist check (baseline/candidate source trees) —
     a violation aborts the round before any game is played;
  2. UCI handshake verification for both engines;
  3. paired-opening, alternating-color games via the internal match runner,
     with Threads=1 / Hash=16 sent to both engines by default;
  4. delta-Elo scoring (ceb.scoring.track_b) and sanitized feedback.

The engines are passed explicitly, so tests use small bundled UCI engines.
For real evaluations both engines must be builds of the pinned Stockfish
(Stockfish 18 / sf_18 / cb3d4ee) with identical compiler flags; see
docs/track_b_stockfish_optimization.md.
"""

import json
import time
from pathlib import Path

from ceb import paths
from ceb.eval_pack import resolve_eval_pack
from ceb.match.internal_runner import play_match
from ceb.match.openings import load_openings_jsonl
from ceb.scoring.track_b import compute_delta_elo_report
from ceb.track_b.diff_policy import check_diff, load_patterns
from ceb.uci.client import UCIClient, EngineError

DEFAULT_UCI_OPTIONS = {"Threads": "1", "Hash": "16"}


class TrackBRoundError(RuntimeError):
    """Round aborted before scoring; message is user-facing."""

    def __init__(self, message, diff_report=None):
        super().__init__(message)
        self.diff_report = diff_report


def _run_diff_check(baseline_src, candidate_src, root):
    track_dir = paths.track_dir("B", root)
    allowed = load_patterns(track_dir / "allowed_paths.txt")
    forbidden = load_patterns(track_dir / "forbidden_paths.txt")
    report = check_diff(baseline_src, candidate_src, allowed, forbidden)
    if not report["passed"]:
        bad = ", ".join(v["path"] for v in report["violations"][:5])
        raise TrackBRoundError(
            "diff whitelist check failed (%d violation(s): %s); round "
            "aborted before any game" % (len(report["violations"]), bad),
            diff_report=report)
    return report


def _verify_handshake(cmd, name):
    try:
        with UCIClient(cmd, name=name) as client:
            return client.handshake() or name
    except EngineError as exc:
        raise TrackBRoundError("%s engine failed UCI handshake: %s" % (name, exc))


def make_track_b_feedback(report):
    """Sanitized agent-facing feedback: aggregates only, no move logs."""
    score = report["score"]
    return {
        "schema": "ceb.track_b.feedback/v1",
        "round": report["round"],
        "games": score["games"],
        "wins": score["wins"],
        "draws": score["draws"],
        "losses": score["losses"],
        "faults": score["faults"],
        "delta_elo": score["delta_elo"],
        "delta_elo_ci95": score["delta_elo_ci95"],
        "penalty_points": score["penalty_points"],
        "final_delta_elo": score["final_delta_elo"],
        "openings_used": len(report.get("openings_used", [])),
    }


def run_track_b_round(candidate_cmd, baseline_cmd, *, round_number=1,
                      run_id="track_b", games=8, movetime_ms=100,
                      max_plies=300, baseline_src=None, candidate_src=None,
                      uci_options=None, eval_pack_dir=None, root=None,
                      runs_root=None, openings_limit=None, engine_jail="none",
                      runner="internal", progress=lambda msg: None):
    """Run one Track B candidate-vs-baseline round.

    Returns (report dict, feedback dict). Raises TrackBRoundError when the
    diff check or a handshake fails (no games are played, nothing scored).
    engine_jail confines the untrusted CANDIDATE engine; the baseline is
    operator-provided and runs on the host.
    """
    if root is None:
        root = paths.find_repo_root()
    runs_root = Path(runs_root) if runs_root else paths.runs_dir(root)

    candidate_cmd = list(candidate_cmd)
    jailed = engine_jail != "none"
    if jailed:
        if len(candidate_cmd) != 1:
            raise TrackBRoundError(
                "--engine-jail requires --candidate-engine to be a single "
                "executable path inside its workspace directory")
        from ceb.jail import engine_command, EngineJailError
        engine_path = Path(candidate_cmd[0]).resolve()
        try:
            candidate_cmd, _ = engine_command(engine_path.parent, engine_jail,
                                              engine_name=engine_path.name)
        except EngineJailError as exc:
            raise TrackBRoundError(exc.public_message)

    diff_report = None
    if baseline_src or candidate_src:
        if not (baseline_src and candidate_src):
            raise TrackBRoundError(
                "diff check needs both --baseline-src and --candidate-src")
        progress("checking candidate diff against the whitelist ...")
        diff_report = _run_diff_check(baseline_src, candidate_src, root)

    try:
        progress("verifying UCI handshakes ...")
        baseline_name = _verify_handshake(baseline_cmd, "baseline")
        candidate_name = _verify_handshake(candidate_cmd, "candidate")

        # Openings: a mounted private pack wins; otherwise the Track B
        # public suite; otherwise fall back to the Track A public openings.
        pack = resolve_eval_pack(root, private_dir=eval_pack_dir, allow_env=True)
        suite = pack.openings
        if pack.source == "public":
            b_suite_path = paths.track_dir("B", root) / "public" / "quick_openings.jsonl"
            if b_suite_path.is_file():
                suite = load_openings_jsonl(b_suite_path)
        if openings_limit:
            suite = suite[:int(openings_limit)]
        pairs = max(1, (games + 1) // 2)
        openings = [suite[k % len(suite)] for k in range(pairs)]

        options = {**DEFAULT_UCI_OPTIONS, **(uci_options or {})}
        progress("playing %d games (movetime %dms, %d opening(s)) ..."
                 % (games, movetime_ms, len(openings)))
        round_dir = runs_root / run_id / ("track_b_round_%d" % round_number)
        round_dir.mkdir(parents=True, exist_ok=True)
        if runner == "fastchess":
            from ceb.match.fastchess_runner import (
                play_match_fastchess, FastchessError)
            try:
                match = play_match_fastchess(
                    list(candidate_cmd), list(baseline_cmd), games=games,
                    movetime_ms=movetime_ms, openings=openings,
                    out_dir=round_dir)
            except FastchessError as exc:
                raise TrackBRoundError(str(exc))
        else:
            match = play_match(
                list(candidate_cmd), list(baseline_cmd),
                games=games, movetime_ms=movetime_ms, max_plies=max_plies,
                candidate_name="candidate", opponent_name="baseline",
                base_seed=1000 * round_number, openings=openings,
                candidate_uci_options=options, opponent_uci_options=options,
                games_text_path=round_dir / "games.txt",
            )
    finally:
        if jailed:
            from ceb.jail import cleanup_jails
            cleanup_jails()

    totals = match["totals"]
    score = compute_delta_elo_report(
        totals["wins"], totals["draws"], totals["losses"],
        faults=match["candidate_faults"])

    report = {
        "schema": "ceb.track_b.round.report/v1",
        "track": "B",
        "run_id": run_id,
        "round": round_number,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "baseline_id": baseline_name,
        "candidate_id": candidate_name,
        "runner": runner,
        "uci_options": options,
        "movetime_ms": movetime_ms,
        "max_plies": max_plies,
        "openings_used": match.get("openings", []),
        "eval_pack": pack.describe(),
        "diff_check": diff_report,
        "totals": totals,
        "candidate_faults": match["candidate_faults"],
        "score": score,
    }
    (round_dir / "match.json").write_text(json.dumps(match, indent=2) + "\n",
                                          encoding="utf-8")
    (round_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n",
                                           encoding="utf-8")
    feedback = make_track_b_feedback(report)
    (round_dir / "feedback.json").write_text(
        json.dumps(feedback, indent=2) + "\n", encoding="utf-8")
    return report, feedback
