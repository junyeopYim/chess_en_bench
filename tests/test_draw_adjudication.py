"""Tests for draw adjudication (P1.3): repetition, insufficient material."""

import json
from pathlib import Path

import pytest

from ceb.chess import parse_fen
from ceb.chess.movegen import is_insufficient_material, repetition_key
from ceb.match.internal_runner import play_game

REPO_ROOT = Path(__file__).resolve().parents[1]

_SCRIPTED_ENGINE = '''#!/usr/bin/env python3
import json, sys
SCRIPT = json.loads(%r)
moves_seen = 0
for raw in sys.stdin:
    tokens = raw.split()
    if not tokens:
        continue
    if tokens[0] == "uci":
        print("id name Scripted")
        print("uciok")
    elif tokens[0] == "isready":
        print("readyok")
    elif tokens[0] == "position":
        moves_seen = len(tokens[tokens.index("moves") + 1:]) \\
            if "moves" in tokens else 0
    elif tokens[0] == "go":
        print("bestmove %%s" %% SCRIPT[moves_seen])
    elif tokens[0] == "quit":
        break
    sys.stdout.flush()
'''


def _scripted_engine(tmp_path, name, script):
    """An engine that answers move script[len(moves played so far)]."""
    path = tmp_path / name
    path.write_text(_SCRIPTED_ENGINE % json.dumps(script))
    path.chmod(0o755)
    return [str(path)]


@pytest.mark.parametrize("fen,expected", [
    ("8/8/8/4k3/8/8/8/4K3 w - - 0 1", True),    # K vs K
    ("8/8/8/4k3/8/8/4B3/4K3 w - - 0 1", True),  # K+B vs K
    ("8/8/8/4k3/8/8/4N3/4K3 w - - 0 1", True),  # K+N vs K
    ("8/8/8/4k3/8/8/4Q3/4K3 w - - 0 1", False),  # K+Q vs K: sufficient
    ("8/8/8/4k3/8/8/4P3/4K3 w - - 0 1", False),  # pawn can promote
    ("8/8/8/4k3/8/8/3NN3/4K3 w - - 0 1", False),  # K+N+N: conservative
    ("8/2b5/8/4k3/8/8/4B3/4K3 w - - 0 1", False),  # B vs B: conservative
])
def test_insufficient_material(fen, expected):
    assert is_insufficient_material(parse_fen(fen)) is expected


def test_repetition_key_ignores_clocks():
    a = parse_fen("4k3/8/8/8/8/8/8/4K3 w - - 0 1")
    b = parse_fen("4k3/8/8/8/8/8/8/4K3 w - - 40 60")
    assert repetition_key(a) == repetition_key(b)
    c = parse_fen("4k3/8/8/8/8/8/8/4K3 b - - 0 1")
    assert repetition_key(a) != repetition_key(c)  # side to move matters


def test_threefold_repetition_drawn(tmp_path):
    shuffle_white = ["g1f3", "f3g1", "g1f3", "f3g1", "g1f3"]
    shuffle_black = ["g8f6", "f6g8", "g8f6", "f6g8", "g8f6"]
    white_script = {}
    # Map by total plies seen: white moves at even counts, black at odd.
    script_by_ply = {}
    for i, mv in enumerate(shuffle_white):
        script_by_ply[2 * i] = mv
    for i, mv in enumerate(shuffle_black):
        script_by_ply[2 * i + 1] = mv
    script = [script_by_ply[i] for i in range(len(script_by_ply))]

    white = _scripted_engine(tmp_path, "white.py", script)
    black = _scripted_engine(tmp_path, "black.py", script)
    record = play_game(white, black, movetime_ms=50, max_plies=40)
    assert record["result"] == "1/2-1/2"
    assert record["reason"] == "threefold repetition"
    # Startpos occurs at ply 0, 4, 8 -> detected before the cap.
    assert record["plies"] == 8


def test_insufficient_material_game_drawn(tmp_path):
    # White captures the last black rook; K vs K must end the game at once.
    start_fen = "8/8/8/4k3/8/8/4r3/4K3 w - - 0 1"
    white = _scripted_engine(tmp_path, "white.py", ["e1e2"])
    black = _scripted_engine(tmp_path, "black.py", ["e5e4"])
    record = play_game(white, black, start_fen=start_fen, movetime_ms=50,
                       max_plies=10)
    assert record["result"] == "1/2-1/2"
    assert record["reason"] == "insufficient material"
    assert record["plies"] == 1


def test_halfmove_threshold_configurable(tmp_path):
    # Rooks keep material sufficient; kings shuffle with the clock at 98 so
    # only the halfmove rule (not insufficient material) can end the game.
    # The scripted engine indexes by TOTAL plies seen, so both sides share a
    # ply-indexed script (white at even plies, black at odd).
    start_fen = "r3k3/8/8/8/8/8/8/R3K3 w - - 98 60"
    script = ["e1d1", "e8d8", "d1e1", "d8e8"]
    white = _scripted_engine(tmp_path, "white.py", script)
    black = _scripted_engine(tmp_path, "black.py", script)
    record = play_game(white, black, start_fen=start_fen, movetime_ms=50,
                       max_plies=10)
    assert record["result"] == "1/2-1/2"
    assert record["reason"] == "fifty-move rule"
    longer = play_game(white, black, start_fen=start_fen, movetime_ms=50,
                       max_plies=4, halfmove_draw_plies=150)
    assert longer["reason"] == "draw adjudicated at max plies"
