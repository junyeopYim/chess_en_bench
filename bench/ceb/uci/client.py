"""Subprocess UCI client.

Submitted engines are untrusted: every read has a timeout, stdout intake is
bounded (backpressure via a bounded queue), stderr is discarded, and the
whole process group is killed on close.
"""

import os
import queue
import signal
import subprocess
import sys
import threading
import time

from ceb.uci import protocol

_MAX_LINE_CHARS = 8192
_QUEUE_MAX_LINES = 10000


class EngineError(Exception):
    """Base class for engine process failures."""


class EngineTimeout(EngineError):
    """Engine did not produce the expected output in time."""


class EngineCrashed(EngineError):
    """Engine process exited or closed its pipes unexpectedly."""


class UCIClient:
    def __init__(self, command, cwd=None, name=None, env=None):
        """command: list of argv strings (never a shell string)."""
        if isinstance(command, str):
            raise TypeError("command must be an argv list, not a string")
        self.command = list(command)
        self.name = name or os.path.basename(self.command[0])
        self.id_name = None
        self._lines = queue.Queue(maxsize=_QUEUE_MAX_LINES)
        self._eof = threading.Event()
        kwargs = {}
        if os.name == "posix":
            kwargs["start_new_session"] = True
        try:
            self.proc = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=cwd,
                env=env,
                text=True,
                bufsize=1,
                **kwargs,
            )
        except OSError as exc:
            raise EngineCrashed("failed to start %s: %s" % (self.command, exc))
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    # ----- low-level I/O ---------------------------------------------------

    def _read_loop(self):
        try:
            for raw in self.proc.stdout:
                self._lines.put(raw[:_MAX_LINE_CHARS].rstrip("\r\n"))
        except (ValueError, OSError):
            pass
        finally:
            self._eof.set()
            self._lines.put(None)  # sentinel so blocked readers wake up

    def send(self, line):
        try:
            self.proc.stdin.write(line + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            raise EngineCrashed("%s: stdin closed (engine died?)" % self.name)

    def read_line(self, timeout):
        """Next stdout line, or raise EngineTimeout / EngineCrashed."""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise EngineTimeout("%s: no output within %.1fs" % (self.name, timeout))
            try:
                line = self._lines.get(timeout=min(remaining, 0.25))
            except queue.Empty:
                continue
            if line is None:
                raise EngineCrashed("%s: engine closed stdout" % self.name)
            return line

    def expect(self, token, timeout):
        """Read lines until one equals `token`; return all lines read."""
        deadline = time.monotonic() + timeout
        seen = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise EngineTimeout("%s: did not see %r within %.1fs"
                                    % (self.name, token, timeout))
            line = self.read_line(remaining)
            seen.append(line)
            if line.strip() == token:
                return seen

    def alive(self):
        return self.proc.poll() is None and not self._eof.is_set()

    # ----- UCI conversation -------------------------------------------------

    def handshake(self, timeout=8.0):
        """uci/uciok then isready/readyok. Returns the engine's id name."""
        self.send("uci")
        for line in self.expect("uciok", timeout):
            name = protocol.parse_id_name(line)
            if name:
                self.id_name = name
        self.sync(timeout)
        return self.id_name

    def sync(self, timeout=8.0):
        """isready/readyok barrier; discards stray output."""
        self.send("isready")
        self.expect("readyok", timeout)

    def new_game(self, timeout=8.0):
        self.send("ucinewgame")
        self.sync(timeout)

    def set_position(self, fen=None, moves=()):
        self.send(protocol.position_command(fen, moves))

    def go_movetime(self, movetime_ms, grace_ms=3000):
        """Send 'go movetime N' and return the bestmove string."""
        self.send("go movetime %d" % movetime_ms)
        timeout = (movetime_ms + grace_ms) / 1000.0
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise EngineTimeout("%s: no bestmove within %.1fs"
                                    % (self.name, timeout))
            line = self.read_line(remaining)
            move = protocol.parse_bestmove(line)
            if move:
                return move

    def go_perft(self, depth, timeout=20.0):
        """Send 'go perft N' (benchmark extension). Returns node count, or
        None when the engine does not support the extension."""
        self.send("go perft %d" % depth)
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                # Engine may be stuck in a normal search; try to stop it.
                try:
                    self.send("stop")
                    self.go_drain(2.0)
                except EngineError:
                    pass
                return None
            try:
                line = self.read_line(remaining)
            except EngineTimeout:
                continue
            nodes = protocol.parse_perft_nodes(line)
            if nodes is not None:
                return nodes
            if protocol.parse_bestmove(line):
                # Engine treated 'go perft' as a normal search: unsupported.
                return None

    def go_drain(self, timeout):
        """Consume output until a bestmove or timeout (best effort)."""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            try:
                line = self.read_line(remaining)
            except EngineError:
                return
            if protocol.parse_bestmove(line):
                return

    # ----- shutdown ----------------------------------------------------------

    def close(self):
        """Polite quit, then terminate/kill the whole process group."""
        if self.proc.poll() is None:
            try:
                self.send("quit")
            except EngineError:
                pass
            try:
                self.proc.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                pass
        if self.proc.poll() is None:
            self._signal_group(signal.SIGTERM)
            try:
                self.proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self._signal_group(signal.SIGKILL)
                try:
                    self.proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    pass
        for stream in (self.proc.stdin, self.proc.stdout):
            try:
                if stream:
                    stream.close()
            except OSError:
                pass

    def _signal_group(self, sig):
        try:
            if os.name == "posix":
                os.killpg(os.getpgid(self.proc.pid), sig)
            else:  # pragma: no cover - windows fallback
                self.proc.terminate() if sig == signal.SIGTERM else self.proc.kill()
        except (ProcessLookupError, PermissionError, OSError):
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def python_engine_command(module, *args):
    """argv for running a benchmark-owned python UCI engine module."""
    return [sys.executable, "-m", module] + list(args)
