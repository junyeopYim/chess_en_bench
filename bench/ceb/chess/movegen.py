"""Legal move generation, attack detection, and move application.

Strategy: generate pseudo-legal moves with (file, rank) delta arithmetic
(no wraparound bugs), then filter by "own king not attacked" using
copy-make. Correct over fast: this is the benchmark oracle, validated by
canonical perft counts in tests.
"""

from ceb.chess.board import (
    Board, WHITE, BLACK, EMPTY,
    is_white_piece, is_black_piece,
)
from ceb.chess.move import Move, PROMOTION_PIECES

KNIGHT_DELTAS = ((1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2))
KING_DELTAS = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))
BISHOP_DIRS = ((1, 1), (1, -1), (-1, 1), (-1, -1))
ROOK_DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1))
QUEEN_DIRS = ROOK_DIRS + BISHOP_DIRS

# Squares whose involvement in a move (as origin or destination) revokes a
# castling right: rook home squares.
_CASTLE_RIGHT_BY_SQUARE = {0: "Q", 7: "K", 56: "q", 63: "k"}


def _shift(sq, df, dr):
    """Square at (file+df, rank+dr) or None if off-board."""
    f = sq % 8 + df
    r = sq // 8 + dr
    if 0 <= f < 8 and 0 <= r < 8:
        return r * 8 + f
    return None


def is_square_attacked(board, sq, by_white):
    """True if `sq` is attacked by any piece of the given color."""
    squares = board.squares

    pawn = "P" if by_white else "p"
    pawn_dr = -1 if by_white else 1  # attacking pawn sits one rank toward its own side
    for df in (-1, 1):
        s = _shift(sq, df, pawn_dr)
        if s is not None and squares[s] == pawn:
            return True

    knight = "N" if by_white else "n"
    for df, dr in KNIGHT_DELTAS:
        s = _shift(sq, df, dr)
        if s is not None and squares[s] == knight:
            return True

    king = "K" if by_white else "k"
    for df, dr in KING_DELTAS:
        s = _shift(sq, df, dr)
        if s is not None and squares[s] == king:
            return True

    rook, bishop, queen = ("R", "B", "Q") if by_white else ("r", "b", "q")
    for dirs, slider in ((ROOK_DIRS, rook), (BISHOP_DIRS, bishop)):
        for df, dr in dirs:
            s = _shift(sq, df, dr)
            while s is not None:
                piece = squares[s]
                if piece != EMPTY:
                    if piece == slider or piece == queen:
                        return True
                    break
                s = _shift(s, df, dr)
    return False


def _add_pawn_move(from_sq, to_sq, promo_rank, moves):
    if to_sq // 8 == promo_rank:
        for promo in PROMOTION_PIECES:
            moves.append(Move(from_sq, to_sq, promo))
    else:
        moves.append(Move(from_sq, to_sq))


def _pawn_moves(board, sq, white, enemy, moves):
    squares = board.squares
    rank = sq // 8
    step = 1 if white else -1
    start_rank = 1 if white else 6
    promo_rank = 7 if white else 0

    one = _shift(sq, 0, step)
    if one is not None and squares[one] == EMPTY:
        _add_pawn_move(sq, one, promo_rank, moves)
        if rank == start_rank:
            two = _shift(sq, 0, 2 * step)
            if two is not None and squares[two] == EMPTY:
                moves.append(Move(sq, two))

    for df in (-1, 1):
        target = _shift(sq, df, step)
        if target is None:
            continue
        if enemy(squares[target]):
            _add_pawn_move(sq, target, promo_rank, moves)
        elif board.ep_square is not None and target == board.ep_square:
            moves.append(Move(sq, target))


def _castling_moves(board, king_sq, white, moves):
    squares = board.squares
    if white:
        if king_sq != 4:
            return
        if ("K" in board.castling and squares[5] == EMPTY and squares[6] == EMPTY
                and squares[7] == "R"
                and not is_square_attacked(board, 4, False)
                and not is_square_attacked(board, 5, False)
                and not is_square_attacked(board, 6, False)):
            moves.append(Move(4, 6))
        if ("Q" in board.castling and squares[3] == EMPTY and squares[2] == EMPTY
                and squares[1] == EMPTY and squares[0] == "R"
                and not is_square_attacked(board, 4, False)
                and not is_square_attacked(board, 3, False)
                and not is_square_attacked(board, 2, False)):
            moves.append(Move(4, 2))
    else:
        if king_sq != 60:
            return
        if ("k" in board.castling and squares[61] == EMPTY and squares[62] == EMPTY
                and squares[63] == "r"
                and not is_square_attacked(board, 60, True)
                and not is_square_attacked(board, 61, True)
                and not is_square_attacked(board, 62, True)):
            moves.append(Move(60, 62))
        if ("q" in board.castling and squares[59] == EMPTY and squares[58] == EMPTY
                and squares[57] == EMPTY and squares[56] == "r"
                and not is_square_attacked(board, 60, True)
                and not is_square_attacked(board, 59, True)
                and not is_square_attacked(board, 58, True)):
            moves.append(Move(60, 58))


def generate_pseudo_legal(board):
    """All pseudo-legal moves for the side to move (king-safety not checked,
    except castling which already requires unattacked transit squares)."""
    moves = []
    white = board.side_to_move == WHITE
    squares = board.squares
    own = is_white_piece if white else is_black_piece
    enemy = is_black_piece if white else is_white_piece

    for sq in range(64):
        piece = squares[sq]
        if piece == EMPTY or not own(piece):
            continue
        kind = piece.upper()
        if kind == "P":
            _pawn_moves(board, sq, white, enemy, moves)
        elif kind == "N":
            for df, dr in KNIGHT_DELTAS:
                t = _shift(sq, df, dr)
                if t is not None and (squares[t] == EMPTY or enemy(squares[t])):
                    moves.append(Move(sq, t))
        elif kind == "K":
            for df, dr in KING_DELTAS:
                t = _shift(sq, df, dr)
                if t is not None and (squares[t] == EMPTY or enemy(squares[t])):
                    moves.append(Move(sq, t))
            _castling_moves(board, sq, white, moves)
        else:
            dirs = ROOK_DIRS if kind == "R" else BISHOP_DIRS if kind == "B" else QUEEN_DIRS
            for df, dr in dirs:
                t = _shift(sq, df, dr)
                while t is not None:
                    target = squares[t]
                    if target == EMPTY:
                        moves.append(Move(sq, t))
                    else:
                        if enemy(target):
                            moves.append(Move(sq, t))
                        break
                    t = _shift(t, df, dr)
    return moves


def make_move(board, move):
    """Apply a move and return the resulting Board (copy-make).

    Assumes the move is pseudo-legal for `board`; the caller is responsible
    for legality filtering (generate_legal does this).
    """
    nb = board.copy()
    squares = nb.squares
    piece = squares[move.from_sq]
    if piece == EMPTY:
        raise ValueError("no piece on %d for move %s" % (move.from_sq, move.uci()))
    target = squares[move.to_sq]
    is_pawn = piece in "Pp"
    is_capture = target != EMPTY

    # En passant capture: pawn moves diagonally onto the empty ep square.
    if (is_pawn and board.ep_square is not None and move.to_sq == board.ep_square
            and move.to_sq % 8 != move.from_sq % 8 and target == EMPTY):
        captured_sq = move.to_sq - 8 if piece == "P" else move.to_sq + 8
        squares[captured_sq] = EMPTY
        is_capture = True

    squares[move.from_sq] = EMPTY
    placed = piece
    if move.promotion:
        placed = move.promotion.upper() if piece == "P" else move.promotion.lower()
    squares[move.to_sq] = placed

    # Castling: king moves two files; relocate the rook.
    if piece == "K" and move.from_sq == 4:
        if move.to_sq == 6:
            squares[7] = EMPTY
            squares[5] = "R"
        elif move.to_sq == 2:
            squares[0] = EMPTY
            squares[3] = "R"
    elif piece == "k" and move.from_sq == 60:
        if move.to_sq == 62:
            squares[63] = EMPTY
            squares[61] = "r"
        elif move.to_sq == 58:
            squares[56] = EMPTY
            squares[59] = "r"

    # Castling rights.
    rights = nb.castling
    if piece == "K":
        rights = rights.replace("K", "").replace("Q", "")
    elif piece == "k":
        rights = rights.replace("k", "").replace("q", "")
    for sq in (move.from_sq, move.to_sq):
        lost = _CASTLE_RIGHT_BY_SQUARE.get(sq)
        if lost:
            rights = rights.replace(lost, "")
    nb.castling = rights

    # En passant target square.
    nb.ep_square = None
    if is_pawn and abs(move.to_sq - move.from_sq) == 16:
        nb.ep_square = (move.from_sq + move.to_sq) // 2

    # Clocks.
    nb.halfmove_clock = 0 if (is_pawn or is_capture) else board.halfmove_clock + 1
    if board.side_to_move == BLACK:
        nb.fullmove_number = board.fullmove_number + 1
    nb.side_to_move = BLACK if board.side_to_move == WHITE else WHITE
    return nb


def in_check(board):
    """True if the side to move is in check."""
    white = board.side_to_move == WHITE
    king_sq = board.king_square(white)
    if king_sq is None:
        return False
    return is_square_attacked(board, king_sq, not white)


def generate_legal(board):
    """All strictly legal moves for the side to move."""
    white = board.side_to_move == WHITE
    legal = []
    for move in generate_pseudo_legal(board):
        nb = make_move(board, move)
        king_sq = nb.king_square(white)
        if king_sq is not None and not is_square_attacked(nb, king_sq, not white):
            legal.append(move)
    return legal


def is_checkmate(board):
    return in_check(board) and not generate_legal(board)


def is_stalemate(board):
    return not in_check(board) and not generate_legal(board)


def is_insufficient_material(board):
    """Dead-draw material: K vs K, K+B vs K, K+N vs K.

    Conservative by design — anything else (including K+N+N vs K and
    opposite-bishop endings) is treated as sufficient.
    """
    minors = []
    for piece in board.squares:
        if piece == EMPTY or piece in "Kk":
            continue
        if piece in "BbNn":
            minors.append(piece)
        else:
            return False  # any pawn, rook, or queen is sufficient
    return len(minors) <= 1


def repetition_key(board):
    """Position identity for repetition detection: placement, side to move,
    castling rights, and en passant square (clocks excluded)."""
    ep = board.ep_square if board.ep_square is not None else -1
    return ("".join(board.squares), board.side_to_move, board.castling, ep)
