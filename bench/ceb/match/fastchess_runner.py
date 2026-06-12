"""Optional fastchess adapter for high-volume matches.

The internal Python runner remains the default and the trusted reference;
fastchess is an opt-in throughput backend (--runner fastchess on
`ceb track-b round run`). When the binary is absent, commands fail with an
actionable message instead of silently falling back.

The adapter builds argv safely (no shell), feeds paired openings via a
generated EPD file, and parses fastchess's W/D/L summary. Reports carry
runner metadata so results from the two backends are distinguishable.
"""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

FASTCHESS_BIN = "fastchess"

# e.g. "Score of candidate vs baseline: 12 - 5 - 3  [0.675] 20"
_SCORE_RE = re.compile(
    r"Score of\s+(?P<a>\S+)\s+vs\s+(?P<b>\S+):\s*"
    r"(?P<w>\d+)\s*-\s*(?P<l>\d+)\s*-\s*(?P<d>\d+)")


class FastchessError(RuntimeError):
    pass


def fastchess_available():
    return shutil.which(FASTCHESS_BIN) is not None


def write_openings_epd(openings, path):
    """EPD file (one FEN per line) for fastchess's opening book input."""
    lines = [o["start_fen"] for o in openings]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return Path(path)


def build_match_argv(candidate_cmd, baseline_cmd, *, games, movetime_ms,
                     epd_path, pgn_out, concurrency=1):
    """fastchess argv for a paired candidate-vs-baseline match.

    Engine commands must be single executable paths (fastchess spawns them
    itself; argv-style python -m commands need a wrapper script).
    """
    def engine_path(cmd, who):
        if len(cmd) != 1:
            raise FastchessError(
                "%s engine must be a single executable path for the "
                "fastchess runner (got %d argv items); use the internal "
                "runner for module-style engines" % (who, len(cmd)))
        return str(Path(cmd[0]).resolve())

    st = max(movetime_ms, 1) / 1000.0
    return [
        FASTCHESS_BIN,
        "-engine", "cmd=%s" % engine_path(candidate_cmd, "candidate"),
        "name=candidate",
        "-engine", "cmd=%s" % engine_path(baseline_cmd, "baseline"),
        "name=baseline",
        "-each", "st=%g" % st, "timemargin=3000",
        "-rounds", str(max(1, games // 2)),
        "-games", "2",  # paired: each opening played with colors swapped
        "-openings", "file=%s" % epd_path, "format=epd", "order=sequential",
        "-pgnout", "file=%s" % pgn_out,
        "-concurrency", str(concurrency),
    ]


def parse_score_output(text):
    """Parse W/D/L (from the first engine's perspective) from fastchess
    output. Returns {"wins","draws","losses"} or raises FastchessError."""
    last = None
    for match in _SCORE_RE.finditer(text):
        last = match
    if last is None:
        raise FastchessError("could not find a 'Score of' line in fastchess "
                             "output")
    return {
        "wins": int(last.group("w")),
        "losses": int(last.group("l")),
        "draws": int(last.group("d")),
        "first_engine": last.group("a"),
    }


def play_match_fastchess(candidate_cmd, baseline_cmd, *, games, movetime_ms,
                         openings, out_dir, concurrency=1, timeout_s=3600):
    """Run a fastchess match. Returns a match-report dict compatible with the
    internal runner's totals/faults shape (faults are not attributed —
    fastchess folds them into game results)."""
    if not fastchess_available():
        raise FastchessError(
            "fastchess binary not found on PATH; install it or use "
            "--runner internal")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".epd", delete=False,
                                     dir=str(out_dir)) as handle:
        epd_path = Path(handle.name)
    write_openings_epd(openings, epd_path)
    pgn_out = out_dir / "fastchess_games.pgn"
    argv = build_match_argv(candidate_cmd, baseline_cmd, games=games,
                            movetime_ms=movetime_ms, epd_path=epd_path,
                            pgn_out=pgn_out, concurrency=concurrency)
    proc = subprocess.run(argv, capture_output=True, text=True,
                          timeout=timeout_s)
    if proc.returncode != 0:
        raise FastchessError("fastchess exited %d: %s"
                             % (proc.returncode, (proc.stderr or "")[-400:]))
    score = parse_score_output(proc.stdout)
    if score["first_engine"] != "candidate":
        score["wins"], score["losses"] = score["losses"], score["wins"]
    return {
        "schema": "ceb.match.report/v1",
        "runner": "fastchess",
        "candidate": "candidate",
        "opponent": "baseline",
        "games_planned": games,
        "movetime_ms": movetime_ms,
        "openings": [o["id"] for o in openings],
        "totals": {"wins": score["wins"], "draws": score["draws"],
                   "losses": score["losses"]},
        "candidate_faults": {"illegal": 0, "timeout": 0, "crash": 0},
        "opponent_faults": {"illegal": 0, "timeout": 0, "crash": 0},
        "pgn": str(pgn_out),
        "note": "fastchess adapter: faults are folded into results, not "
                "attributed; internal oracle post-validation of PGN is "
                "future work",
    }
