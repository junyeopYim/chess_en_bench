"""Move representation and UCI move-string conversion."""

from ceb.chess.board import square_index, square_name

PROMOTION_PIECES = "qrbn"


class Move:
    """A move as (from_sq, to_sq, optional promotion piece in 'qrbn').

    Castling is encoded as the king's two-file move (e1g1, e1c1, ...).
    En passant is encoded as the pawn's diagonal move to the ep square.
    """

    __slots__ = ("from_sq", "to_sq", "promotion")

    def __init__(self, from_sq, to_sq, promotion=None):
        self.from_sq = from_sq
        self.to_sq = to_sq
        self.promotion = promotion

    def uci(self):
        return square_name(self.from_sq) + square_name(self.to_sq) + (self.promotion or "")

    @classmethod
    def from_uci(cls, text):
        """Parse 'e2e4' / 'e7e8q'. Raises ValueError on malformed input."""
        text = text.strip()
        if len(text) not in (4, 5):
            raise ValueError("bad UCI move: %r" % (text,))
        from_sq = square_index(text[0:2])
        to_sq = square_index(text[2:4])
        promotion = None
        if len(text) == 5:
            promotion = text[4].lower()
            if promotion not in PROMOTION_PIECES:
                raise ValueError("bad promotion piece in %r" % (text,))
        return cls(from_sq, to_sq, promotion)

    def __eq__(self, other):
        return (isinstance(other, Move)
                and self.from_sq == other.from_sq
                and self.to_sq == other.to_sq
                and self.promotion == other.promotion)

    def __hash__(self):
        return hash((self.from_sq, self.to_sq, self.promotion))

    def __repr__(self):
        return "Move(%s)" % self.uci()
