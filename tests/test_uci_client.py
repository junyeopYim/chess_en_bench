"""Tests for ceb.uci.client against the bundled example engine and opponents."""

import subprocess
import sys
from pathlib import Path

import pytest

from ceb.chess import parse_fen, generate_legal
from ceb.uci.client import UCIClient

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples" / "submissions" / "minimal_uci_engine_python"


@pytest.fixture(scope="module")
def example_engine_cmd():
    subprocess.run(["bash", str(EXAMPLE / "build.sh")], check=True,
                   capture_output=True, timeout=60)
    return [str(EXAMPLE / "engine")]


def test_handshake_and_legal_bestmove(example_engine_cmd):
    with UCIClient(example_engine_cmd, cwd=str(EXAMPLE)) as client:
        name = client.handshake()
        assert name and "MinimalFirstMove" in name
        client.new_game()
        client.set_position()  # startpos
        best = client.go_movetime(100)
        legal = {m.uci() for m in generate_legal(
            parse_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"))}
        assert best in legal


def test_bestmove_from_fen_position(example_engine_cmd):
    fen = "8/P7/8/8/8/8/k6K/8 w - - 0 1"
    with UCIClient(example_engine_cmd, cwd=str(EXAMPLE)) as client:
        client.handshake()
        client.set_position(fen)
        best = client.go_movetime(100)
        assert best in {m.uci() for m in generate_legal(parse_fen(fen))}


def test_perft_extension(example_engine_cmd):
    with UCIClient(example_engine_cmd, cwd=str(EXAMPLE)) as client:
        client.handshake()
        client.set_position()
        assert client.go_perft(2, timeout=30.0) == 400


def test_opponent_speaks_uci():
    cmd = [sys.executable, "-m", "ceb.match.opponents", "BenchRandom"]
    with UCIClient(cmd) as client:
        client.handshake()
        client.set_position(None, ["e2e4"])
        best = client.go_movetime(50)
        board = parse_fen("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1")
        assert best in {m.uci() for m in generate_legal(board)}


def test_close_kills_process(example_engine_cmd):
    client = UCIClient(example_engine_cmd, cwd=str(EXAMPLE))
    client.handshake()
    client.close()
    assert client.proc.poll() is not None
