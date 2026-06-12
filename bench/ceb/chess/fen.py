"""FEN parsing and generation."""

from ceb.chess.board import (
    Board, WHITE, BLACK, EMPTY, FILES, RANKS,
    WHITE_PIECES, BLACK_PIECES, square_index, square_name,
)

_ALL_PIECES = WHITE_PIECES + BLACK_PIECES


def parse_fen(fen):
    """Parse a FEN string into a Board. Raises ValueError on malformed input.

    The halfmove clock and fullmove number fields are optional (default 0/1),
    which tolerates 4-field FENs that some engines emit.
    """
    if not isinstance(fen, str):
        raise ValueError("FEN must be a string")
    fields = fen.split()
    if len(fields) < 4:
        raise ValueError("FEN needs at least 4 fields: %r" % (fen,))

    placement, side, castling, ep = fields[0], fields[1], fields[2], fields[3]
    halfmove = fields[4] if len(fields) > 4 else "0"
    fullmove = fields[5] if len(fields) > 5 else "1"

    board = Board()
    ranks = placement.split("/")
    if len(ranks) != 8:
        raise ValueError("FEN placement must have 8 ranks: %r" % (placement,))
    for rank_idx, rank_str in enumerate(ranks):
        rank = 7 - rank_idx  # FEN starts at rank 8
        file = 0
        for ch in rank_str:
            if ch.isdigit():
                step = int(ch)
                if not 1 <= step <= 8:
                    raise ValueError("bad empty-run in FEN rank: %r" % (rank_str,))
                file += step
            elif ch in _ALL_PIECES:
                if file > 7:
                    raise ValueError("FEN rank overflow: %r" % (rank_str,))
                board.squares[rank * 8 + file] = ch
                file += 1
            else:
                raise ValueError("bad piece char %r in FEN" % (ch,))
        if file != 8:
            raise ValueError("FEN rank %r does not sum to 8 files" % (rank_str,))

    if board.squares.count("K") != 1 or board.squares.count("k") != 1:
        raise ValueError("FEN must contain exactly one king per side")

    if side not in (WHITE, BLACK):
        raise ValueError("bad side-to-move field: %r" % (side,))
    board.side_to_move = side

    if castling == "-":
        board.castling = ""
    else:
        seen = []
        for ch in castling:
            if ch not in "KQkq" or ch in seen:
                raise ValueError("bad castling field: %r" % (castling,))
            seen.append(ch)
        # Normalize to KQkq order.
        board.castling = "".join(c for c in "KQkq" if c in seen)

    if ep == "-":
        board.ep_square = None
    else:
        sq = square_index(ep)  # raises on malformed
        if sq // 8 not in (2, 5):
            raise ValueError("en passant square must be on rank 3 or 6: %r" % (ep,))
        board.ep_square = sq

    try:
        board.halfmove_clock = int(halfmove)
        board.fullmove_number = int(fullmove)
    except ValueError:
        raise ValueError("bad move counters in FEN: %r" % (fen,))
    if board.halfmove_clock < 0 or board.fullmove_number < 1:
        raise ValueError("bad move counters in FEN: %r" % (fen,))
    return board


def board_to_fen(board):
    """Serialize a Board back to a 6-field FEN string."""
    rank_strs = []
    for rank in range(7, -1, -1):
        run = 0
        out = []
        for file in range(8):
            piece = board.squares[rank * 8 + file]
            if piece == EMPTY:
                run += 1
            else:
                if run:
                    out.append(str(run))
                    run = 0
                out.append(piece)
        if run:
            out.append(str(run))
        rank_strs.append("".join(out))
    placement = "/".join(rank_strs)
    castling = board.castling if board.castling else "-"
    ep = square_name(board.ep_square) if board.ep_square is not None else "-"
    return "%s %s %s %s %d %d" % (
        placement, board.side_to_move, castling, ep,
        board.halfmove_clock, board.fullmove_number,
    )
