"""Public correctness gate for Track A submissions.

Checks (in order; a hard failure skips the remaining heavy checks):
  format      workspace layout (engine or build.sh present)
  build       run build.sh if present
  engine      executable ./engine resolved after build
  handshake   uci/uciok + isready/readyok
  position    position startpos / position fen accepted
  bestmove    legal bestmove on public FENs (oracle-validated)
  perft       'go perft' extension vs oracle counts (recommended -> warn)
  time        'go movetime' returns within budget
  mini_match  short match vs BenchRandom: no candidate faults

The gate may be run unlimited times and never consumes official round budget.

Strict mode (run_gate(strict=True), used by official rounds): the 'go perft'
extension is REQUIRED — missing support or wrong counts fail the gate. An
eval pack (ceb.eval_pack) can extend the FEN/perft sets; failure details
quote row ids only, never raw FENs, so hidden positions cannot leak.
"""

import json
import os
import stat
import subprocess
import time
from pathlib import Path

from ceb import paths
from ceb.chess import parse_fen, generate_legal, Move
from ceb.chess.perft import perft
from ceb.config import load_gate_config
from ceb.gate.reports import (
    GateReport, CheckResult, STATUS_PASS, STATUS_FAIL, STATUS_WARN, STATUS_SKIP,
)
from ceb.match.internal_runner import play_match
from ceb.match.opponents import opponent_command
from ceb.uci.client import UCIClient, EngineError, EngineTimeout

DEFAULT_GATE_CONFIG = {
    "handshake_timeout_s": 8,
    "bestmove_movetime_ms": 200,
    "bestmove_grace_ms": 3000,
    "max_bestmove_failures": 2,
    "perft_required": False,
    "perft_max_depth": 3,
    "time_check_movetime_ms": 100,
    "time_check_budget_ms": 2500,
    "mini_match": {
        "enabled": True,
        "games": 2,
        "movetime_ms": 50,
        "max_plies": 60,
        "opponent": "BenchRandom",
    },
}


def _load_jsonl(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_public_fens(root=None):
    return _load_jsonl(paths.track_dir("A", root) / "public" / "fen_examples.jsonl")


def load_public_perft(root=None):
    return _load_jsonl(paths.track_dir("A", root) / "public" / "perft_examples.jsonl")


def _merged_gate_config(root):
    config = {k: (dict(v) if isinstance(v, dict) else v)
              for k, v in DEFAULT_GATE_CONFIG.items()}
    try:
        loaded = load_gate_config(root)
    except (FileNotFoundError, ValueError):
        return config
    for key, value in (loaded or {}).items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            config[key].update(value)
        else:
            config[key] = value
    return config


class _Gate:
    def __init__(self, workspace, track, root, quick_match, strict, pack):
        self.workspace = Path(workspace).resolve()
        self.root = root
        self.strict = strict
        self.pack = pack
        self.config = _merged_gate_config(root)
        if strict:
            self.config["perft_required"] = True
        if not quick_match:
            self.config["mini_match"]["enabled"] = False
        self.report = GateReport(track, self.workspace, strict=strict)
        self.engine_cmd = None

    def _timed(self, check_id, name, fn):
        start = time.monotonic()
        try:
            status, details = fn()
        except Exception as exc:  # noqa: BLE001 - gate must report, not crash
            status, details = STATUS_FAIL, "unexpected error: %s" % exc
        result = CheckResult(check_id, name, status, details,
                             (time.monotonic() - start) * 1000)
        self.report.add(result)
        return result

    def _skip(self, check_id, name, why="skipped after earlier failure"):
        self.report.add(CheckResult(check_id, name, STATUS_SKIP, why))

    # ----- checks -----------------------------------------------------------

    def check_format(self):
        if not self.workspace.is_dir():
            return STATUS_FAIL, "workspace directory not found: %s" % self.workspace
        engine = self.workspace / "engine"
        build = self.workspace / "build.sh"
        if not engine.exists() and not build.exists():
            return STATUS_FAIL, "need ./engine or build.sh in the workspace"
        return STATUS_PASS, "workspace layout ok"

    def check_build(self):
        build = self.workspace / "build.sh"
        if not build.exists():
            return STATUS_PASS, "no build.sh (prebuilt engine)"
        try:
            proc = subprocess.run(
                ["bash", str(build)], cwd=str(self.workspace),
                capture_output=True, text=True, timeout=120,
            )
        except subprocess.TimeoutExpired:
            return STATUS_FAIL, "build.sh exceeded 120s"
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip()[-300:]
            return STATUS_FAIL, "build.sh exited %d: %s" % (proc.returncode, tail)
        return STATUS_PASS, "build.sh ok"

    def resolve_engine(self):
        engine = self.workspace / "engine"
        if not engine.is_file():
            return STATUS_FAIL, "no ./engine after build"
        mode = engine.stat().st_mode
        if not mode & stat.S_IXUSR:
            try:
                engine.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            except OSError:
                return STATUS_FAIL, "./engine is not executable"
        self.engine_cmd = [str(engine)]
        return STATUS_PASS, "engine executable found"

    def _client(self):
        return UCIClient(self.engine_cmd, cwd=str(self.workspace), name="candidate")

    def check_handshake(self):
        timeout = float(self.config["handshake_timeout_s"])
        with self._client() as client:
            name = client.handshake(timeout=timeout)
        return STATUS_PASS, "id name: %s" % (name or "(not reported)")

    def check_position(self):
        timeout = float(self.config["handshake_timeout_s"])
        sample_fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
        with self._client() as client:
            client.handshake(timeout=timeout)
            client.set_position()  # startpos
            client.sync(timeout)
            client.set_position(sample_fen)
            client.sync(timeout)
            client.set_position(None, ["e2e4", "e7e5"])
            client.sync(timeout)
        return STATUS_PASS, "startpos / fen / moves accepted"

    def check_bestmove(self):
        movetime = int(self.config["bestmove_movetime_ms"])
        grace = int(self.config["bestmove_grace_ms"])
        max_failures = int(self.config["max_bestmove_failures"])
        failures = []
        tested = 0
        with self._client() as client:
            client.handshake(timeout=float(self.config["handshake_timeout_s"]))
            client.new_game()
            for i, row in enumerate(self.pack.fens):
                fen = row["fen"]
                row_id = row.get("id") or "fen_%d" % i  # ids only: never leak FENs
                try:
                    board = parse_fen(fen)
                except ValueError:
                    # Never echo the FEN: hidden-pack rows must not leak
                    # through error messages.
                    failures.append("%s: invalid FEN row in eval pack "
                                    "(content withheld)" % row_id)
                    if len(failures) >= max_failures:
                        break
                    continue
                legal = {m.uci() for m in generate_legal(board)}
                if not legal:
                    continue  # terminal positions are not bestmove material
                tested += 1
                try:
                    client.set_position(fen)
                    best = client.go_movetime(movetime, grace_ms=grace)
                except EngineError as exc:
                    failures.append("%s: %s" % (row_id, exc))
                else:
                    if best not in legal:
                        failures.append("%s: illegal bestmove %r" % (row_id, best))
                if len(failures) >= max_failures:
                    break
        if failures:
            return STATUS_FAIL, "; ".join(failures[:3])
        return STATUS_PASS, "legal bestmove on %d positions" % tested

    def check_perft(self):
        required = bool(self.config["perft_required"])
        max_depth = int(self.config["perft_max_depth"])
        rows = [r for r in self.pack.perft if r["depth"] <= max_depth]
        with self._client() as client:
            client.handshake(timeout=float(self.config["handshake_timeout_s"]))
            checked = 0
            for i, row in enumerate(rows):
                row_id = row.get("id") or "perft_%d" % i  # ids only: never leak FENs
                client.set_position(row["fen"])
                client.sync()
                nodes = client.go_perft(row["depth"], timeout=20.0)
                if nodes is None:
                    msg = ("'go perft' extension not supported (%s, see "
                           "specs/uci_extension_perft.md)"
                           % ("required in strict mode" if required else "recommended"))
                    return (STATUS_FAIL if required else STATUS_WARN), msg
                expected = row["nodes"]
                if nodes != expected:
                    return STATUS_FAIL, ("perft mismatch on %s depth %d: got %d, "
                                         "expected %d" % (row_id, row["depth"],
                                                          nodes, expected))
                checked += 1
                client.sync()
        return STATUS_PASS, "perft verified on %d position/depth pairs" % checked

    def check_time_management(self):
        movetime = int(self.config["time_check_movetime_ms"])
        budget_ms = int(self.config["time_check_budget_ms"])
        with self._client() as client:
            client.handshake(timeout=float(self.config["handshake_timeout_s"]))
            client.set_position()
            start = time.monotonic()
            try:
                client.go_movetime(movetime, grace_ms=budget_ms)
            except EngineTimeout:
                return STATUS_FAIL, ("no bestmove within movetime %dms + %dms budget"
                                     % (movetime, budget_ms))
            elapsed_ms = (time.monotonic() - start) * 1000
        if elapsed_ms > movetime + budget_ms:
            return STATUS_FAIL, "bestmove took %.0fms" % elapsed_ms
        return STATUS_PASS, "bestmove in %.0fms for movetime %dms" % (elapsed_ms, movetime)

    def check_mini_match(self):
        cfg = self.config["mini_match"]
        if not cfg.get("enabled", True):
            return STATUS_SKIP, "mini match disabled"
        report = play_match(
            self.engine_cmd, opponent_command(cfg.get("opponent", "BenchRandom")),
            games=int(cfg.get("games", 2)),
            movetime_ms=int(cfg.get("movetime_ms", 50)),
            max_plies=int(cfg.get("max_plies", 60)),
            candidate_name="candidate",
            opponent_name=cfg.get("opponent", "BenchRandom"),
            candidate_cwd=str(self.workspace),
        )
        faults = report["candidate_faults"]
        total_faults = sum(faults.values())
        totals = report["totals"]
        summary = "W%d D%d L%d vs %s" % (
            totals["wins"], totals["draws"], totals["losses"], report["opponent"])
        if total_faults:
            return STATUS_FAIL, "%s; candidate faults: %s" % (summary, faults)
        return STATUS_PASS, "%s; no faults" % summary

    # ----- driver -------------------------------------------------------------

    def run(self):
        order = [
            ("format", "workspace format", self.check_format, True),
            ("build", "build check", self.check_build, True),
            ("engine", "engine binary", self.resolve_engine, True),
            ("handshake", "UCI handshake", self.check_handshake, True),
            ("position", "position commands", self.check_position, True),
            ("bestmove", "legal bestmove", self.check_bestmove, True),
            ("perft", "perft extension", self.check_perft, self.strict),
            ("time", "time management", self.check_time_management, True),
            ("mini_match", "mini match smoke", self.check_mini_match, True),
        ]
        aborted = False
        for check_id, name, fn, hard in order:
            if aborted:
                self._skip(check_id, name)
                continue
            result = self._timed(check_id, name, fn)
            if result.status == STATUS_FAIL and hard:
                aborted = True
        self.report.finish()
        return self.report


def run_gate(workspace, track="A", root=None, quick_match=True, strict=False,
             eval_pack=None):
    """Run the gate against a submission workspace. Returns GateReport.

    strict: official-round policy — 'go perft' becomes mandatory.
    eval_pack: a ceb.eval_pack.EvalPack supplying the FEN/perft sets;
    defaults to the public pack.
    """
    if root is None:
        root = paths.find_repo_root()
    if str(track).upper() not in ("A", "A_FROM_SCRATCH"):
        raise ValueError("the public gate currently supports track A only")
    if eval_pack is None:
        from ceb.eval_pack import load_public_pack
        eval_pack = load_public_pack(root)
    return _Gate(workspace, "A", root, quick_match, strict, eval_pack).run()


def save_gate_report(report, out_path=None, root=None):
    """Persist the gate report JSON; returns the path written."""
    if out_path is None:
        gate_dir = paths.runs_dir(root) / "_gate"
        gate_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out_path = gate_dir / ("%s-%s.json" % (Path(report.workspace).name, stamp))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report.to_json() + os.linesep, encoding="utf-8")
    return out_path
