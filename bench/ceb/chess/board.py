"""Board representation: 64-square mailbox list, index 0 = a1, 63 = h8.

White pieces are uppercase ("PNBRQK"), black are lowercase ("pnbrqk"),
empty squares are ".".
"""

WHITE = "w"
BLACK = "b"
EMPTY = "."

FILES = "abcdefgh"
RANKS = "12345678"

WHITE_PIECES = "PNBRQK"
BLACK_PIECES = "pnbrqk"

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def square_index(name):
    """'e4' -> 28. Raises ValueError on malformed names."""
    if len(name) != 2 or name[0] not in FILES or name[1] not in RANKS:
        raise ValueError("bad square name: %r" % (name,))
    return RANKS.index(name[1]) * 8 + FILES.index(name[0])


def square_name(index):
    """28 -> 'e4'."""
    if not 0 <= index < 64:
        raise ValueError("bad square index: %r" % (index,))
    return FILES[index % 8] + RANKS[index // 8]


def is_white_piece(piece):
    return piece in WHITE_PIECES


def is_black_piece(piece):
    return piece in BLACK_PIECES


class Board:
    """Mutable position. Use .copy() + movegen.make_move for search."""

    __slots__ = ("squares", "side_to_move", "castling", "ep_square",
                 "halfmove_clock", "fullmove_number")

    def __init__(self):
        self.squares = [EMPTY] * 64
        self.side_to_move = WHITE
        self.castling = ""          # subset of "KQkq", "" means none
        self.ep_square = None       # int square index or None
        self.halfmove_clock = 0
        self.fullmove_number = 1

    def copy(self):
        b = Board.__new__(Board)
        b.squares = self.squares[:]
        b.side_to_move = self.side_to_move
        b.castling = self.castling
        b.ep_square = self.ep_square
        b.halfmove_clock = self.halfmove_clock
        b.fullmove_number = self.fullmove_number
        return b

    def piece_at(self, sq):
        return self.squares[sq]

    def king_square(self, white):
        target = "K" if white else "k"
        squares = self.squares
        for i in range(64):
            if squares[i] == target:
                return i
        return None

    def white_to_move(self):
        return self.side_to_move == WHITE

    def __repr__(self):
        from ceb.chess.fen import board_to_fen
        return "Board(%r)" % board_to_fen(self)
