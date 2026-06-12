"""Internal chess oracle: board, FEN, move generation, perft.

This module is the benchmark's source of truth for legality. It is
intentionally dependency-free so the benchmark can enforce "from scratch"
principles for evaluated agents without itself relying on external chess
libraries.
"""

from ceb.chess.board import Board, WHITE, BLACK, EMPTY, START_FEN, square_index, square_name
from ceb.chess.fen import parse_fen, board_to_fen
from ceb.chess.move import Move
from ceb.chess.movegen import (
    generate_legal,
    generate_pseudo_legal,
    is_square_attacked,
    in_check,
    make_move,
    is_checkmate,
    is_stalemate,
)
from ceb.chess.perft import perft

__all__ = [
    "Board", "WHITE", "BLACK", "EMPTY", "START_FEN",
    "square_index", "square_name",
    "parse_fen", "board_to_fen",
    "Move",
    "generate_legal", "generate_pseudo_legal", "is_square_attacked",
    "in_check", "make_move", "is_checkmate", "is_stalemate",
    "perft",
]
