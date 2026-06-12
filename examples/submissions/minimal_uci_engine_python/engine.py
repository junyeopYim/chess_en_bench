#!/usr/bin/env python3
"""Minimal self-contained UCI engine that passes the chess_en_bench public gate.

It plays the first legal move in deterministic (UCI-string) order and
supports the benchmark's `go perft <depth>` extension. It also answers the
`bench` command with deterministic `Nodes searched` / `Nodes/second` lines (a
fixed perft node count), so it can stand in as a bench-capable toy engine for
the Track B speed-sanity path in tests and the public-official smoke recipe.

This file is intentionally self-contained (no imports from the `ceb`
package): official external submissions must run without the benchmark's
Python environment. The legality logic is a condensed copy of the
benchmark oracle, included here for demonstration only — a real Track A
submission must implement its own chess logic from scratch.
"""

import sys

EMPTY = "."
FILES = "abcdefgh"
RANKS = "12345678"
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

KNIGHT_DELTAS = ((1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2))
KING_DELTAS = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))
BISHOP_DIRS = ((1, 1), (1, -1), (-1, 1), (-1, -1))
ROOK_DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1))
QUEEN_DIRS = ROOK_DIRS + BISHOP_DIRS
CASTLE_RIGHT_BY_SQUARE = {0: "Q", 7: "K", 56: "q", 63: "k"}


def sq_index(name):
    return RANKS.index(name[1]) * 8 + FILES.index(name[0])


def sq_name(index):
    return FILES[index % 8] + RANKS[index // 8]


def shift(sq, df, dr):
    f = sq % 8 + df
    r = sq // 8 + dr
    if 0 <= f < 8 and 0 <= r < 8:
        return r * 8 + f
    return None


class Position:
    __slots__ = ("squares", "white_to_move", "castling", "ep", "halfmove", "fullmove")

    def copy(self):
        p = Position.__new__(Position)
        p.squares = self.squares[:]
        p.white_to_move = self.white_to_move
        p.castling = self.castling
        p.ep = self.ep
        p.halfmove = self.halfmove
        p.fullmove = self.fullmove
        return p


def parse_fen(fen):
    fields = fen.split()
    pos = Position.__new__(Position)
    pos.squares = [EMPTY] * 64
    for rank_idx, rank_str in enumerate(fields[0].split("/")):
        rank = 7 - rank_idx
        file = 0
        for ch in rank_str:
            if ch.isdigit():
                file += int(ch)
            else:
                pos.squares[rank * 8 + file] = ch
                file += 1
    pos.white_to_move = fields[1] == "w"
    pos.castling = "" if fields[2] == "-" else fields[2]
    pos.ep = None if fields[3] == "-" else sq_index(fields[3])
    pos.halfmove = int(fields[4]) if len(fields) > 4 else 0
    pos.fullmove = int(fields[5]) if len(fields) > 5 else 1
    return pos


def is_attacked(pos, sq, by_white):
    squares = pos.squares
    pawn, pawn_dr = ("P", -1) if by_white else ("p", 1)
    for df in (-1, 1):
        s = shift(sq, df, pawn_dr)
        if s is not None and squares[s] == pawn:
            return True
    for deltas, piece in ((KNIGHT_DELTAS, "N" if by_white else "n"),
                          (KING_DELTAS, "K" if by_white else "k")):
        for df, dr in deltas:
            s = shift(sq, df, dr)
            if s is not None and squares[s] == piece:
                return True
    rook, bishop, queen = ("R", "B", "Q") if by_white else ("r", "b", "q")
    for dirs, slider in ((ROOK_DIRS, rook), (BISHOP_DIRS, bishop)):
        for df, dr in dirs:
            s = shift(sq, df, dr)
            while s is not None:
                piece = squares[s]
                if piece != EMPTY:
                    if piece == slider or piece == queen:
                        return True
                    break
                s = shift(s, df, dr)
    return False


def pseudo_moves(pos):
    """Yields (from_sq, to_sq, promotion-or-None)."""
    moves = []
    white = pos.white_to_move
    squares = pos.squares
    own = str.isupper if white else str.islower

    def enemy(piece):
        return piece != EMPTY and not own(piece)

    for sq in range(64):
        piece = squares[sq]
        if piece == EMPTY or not own(piece):
            continue
        kind = piece.upper()
        if kind == "P":
            step = 1 if white else -1
            start_rank = 1 if white else 6
            promo_rank = 7 if white else 0
            one = shift(sq, 0, step)
            if one is not None and squares[one] == EMPTY:
                if one // 8 == promo_rank:
                    for pr in "qrbn":
                        moves.append((sq, one, pr))
                else:
                    moves.append((sq, one, None))
                if sq // 8 == start_rank:
                    two = shift(sq, 0, 2 * step)
                    if two is not None and squares[two] == EMPTY:
                        moves.append((sq, two, None))
            for df in (-1, 1):
                t = shift(sq, df, step)
                if t is None:
                    continue
                if enemy(squares[t]):
                    if t // 8 == promo_rank:
                        for pr in "qrbn":
                            moves.append((sq, t, pr))
                    else:
                        moves.append((sq, t, None))
                elif pos.ep is not None and t == pos.ep:
                    moves.append((sq, t, None))
        elif kind == "N":
            for df, dr in KNIGHT_DELTAS:
                t = shift(sq, df, dr)
                if t is not None and (squares[t] == EMPTY or enemy(squares[t])):
                    moves.append((sq, t, None))
        elif kind == "K":
            for df, dr in KING_DELTAS:
                t = shift(sq, df, dr)
                if t is not None and (squares[t] == EMPTY or enemy(squares[t])):
                    moves.append((sq, t, None))
            if white and sq == 4:
                if ("K" in pos.castling and squares[5] == EMPTY and squares[6] == EMPTY
                        and squares[7] == "R"
                        and not is_attacked(pos, 4, False)
                        and not is_attacked(pos, 5, False)
                        and not is_attacked(pos, 6, False)):
                    moves.append((4, 6, None))
                if ("Q" in pos.castling and squares[3] == EMPTY and squares[2] == EMPTY
                        and squares[1] == EMPTY and squares[0] == "R"
                        and not is_attacked(pos, 4, False)
                        and not is_attacked(pos, 3, False)
                        and not is_attacked(pos, 2, False)):
                    moves.append((4, 2, None))
            elif not white and sq == 60:
                if ("k" in pos.castling and squares[61] == EMPTY and squares[62] == EMPTY
                        and squares[63] == "r"
                        and not is_attacked(pos, 60, True)
                        and not is_attacked(pos, 61, True)
                        and not is_attacked(pos, 62, True)):
                    moves.append((60, 62, None))
                if ("q" in pos.castling and squares[59] == EMPTY and squares[58] == EMPTY
                        and squares[57] == EMPTY and squares[56] == "r"
                        and not is_attacked(pos, 60, True)
                        and not is_attacked(pos, 59, True)
                        and not is_attacked(pos, 58, True)):
                    moves.append((60, 58, None))
        else:
            dirs = ROOK_DIRS if kind == "R" else BISHOP_DIRS if kind == "B" else QUEEN_DIRS
            for df, dr in dirs:
                t = shift(sq, df, dr)
                while t is not None:
                    target = squares[t]
                    if target == EMPTY:
                        moves.append((sq, t, None))
                    else:
                        if enemy(target):
                            moves.append((sq, t, None))
                        break
                    t = shift(t, df, dr)
    return moves


def apply_move(pos, move):
    from_sq, to_sq, promotion = move
    np = pos.copy()
    squares = np.squares
    piece = squares[from_sq]
    target = squares[to_sq]
    is_pawn = piece in "Pp"
    capture = target != EMPTY

    if (is_pawn and pos.ep is not None and to_sq == pos.ep
            and to_sq % 8 != from_sq % 8 and target == EMPTY):
        squares[to_sq - 8 if piece == "P" else to_sq + 8] = EMPTY
        capture = True

    squares[from_sq] = EMPTY
    placed = piece
    if promotion:
        placed = promotion.upper() if piece == "P" else promotion
    squares[to_sq] = placed

    if piece == "K" and from_sq == 4:
        if to_sq == 6:
            squares[7], squares[5] = EMPTY, "R"
        elif to_sq == 2:
            squares[0], squares[3] = EMPTY, "R"
    elif piece == "k" and from_sq == 60:
        if to_sq == 62:
            squares[63], squares[61] = EMPTY, "r"
        elif to_sq == 58:
            squares[56], squares[59] = EMPTY, "r"

    rights = np.castling
    if piece == "K":
        rights = rights.replace("K", "").replace("Q", "")
    elif piece == "k":
        rights = rights.replace("k", "").replace("q", "")
    for sq in (from_sq, to_sq):
        lost = CASTLE_RIGHT_BY_SQUARE.get(sq)
        if lost:
            rights = rights.replace(lost, "")
    np.castling = rights

    np.ep = None
    if is_pawn and abs(to_sq - from_sq) == 16:
        np.ep = (from_sq + to_sq) // 2
    np.halfmove = 0 if (is_pawn or capture) else pos.halfmove + 1
    if not pos.white_to_move:
        np.fullmove = pos.fullmove + 1
    np.white_to_move = not pos.white_to_move
    return np


def king_square(pos, white):
    return pos.squares.index("K" if white else "k")


def legal_moves(pos):
    white = pos.white_to_move
    out = []
    for move in pseudo_moves(pos):
        np = apply_move(pos, move)
        if not is_attacked(np, king_square(np, white), not white):
            out.append(move)
    return out


def move_to_uci(move):
    from_sq, to_sq, promotion = move
    return sq_name(from_sq) + sq_name(to_sq) + (promotion or "")


def perft(pos, depth):
    moves = legal_moves(pos)
    if depth <= 1:
        return len(moves) if depth == 1 else 1
    return sum(perft(apply_move(pos, m), depth - 1) for m in moves)


def parse_position(tokens):
    pos = parse_fen(START_FEN)
    idx = 0
    if tokens and tokens[0] == "startpos":
        idx = 1
    elif tokens and tokens[0] == "fen":
        end = tokens.index("moves") if "moves" in tokens else len(tokens)
        pos = parse_fen(" ".join(tokens[1:end]))
        idx = end
    if idx < len(tokens) and tokens[idx] == "moves":
        for uci in tokens[idx + 1:]:
            from_sq, to_sq = sq_index(uci[0:2]), sq_index(uci[2:4])
            promotion = uci[4].lower() if len(uci) == 5 else None
            pos = apply_move(pos, (from_sq, to_sq, promotion))
    return pos


def main():
    pos = parse_fen(START_FEN)
    for raw in sys.stdin:
        tokens = raw.split()
        if not tokens:
            continue
        cmd = tokens[0]
        if cmd == "uci":
            print("id name MinimalFirstMove 0.1")
            print("id author chess_en_bench example")
            print("uciok")
        elif cmd == "isready":
            print("readyok")
        elif cmd == "ucinewgame":
            pos = parse_fen(START_FEN)
        elif cmd == "bench":
            # Deterministic node count (perft from the start position). Both a
            # baseline and a candidate built from this engine report the same
            # value, so the candidate/baseline NPS ratio is ~1.0.
            nodes = perft(parse_fen(START_FEN), 3)
            print("Nodes searched  : %d" % nodes)
            print("Nodes/second    : %d" % (nodes * 1000))
        elif cmd == "position":
            try:
                pos = parse_position(tokens[1:])
            except (ValueError, IndexError):
                pass
        elif cmd == "go":
            if len(tokens) >= 3 and tokens[1] == "perft":
                print("info string perft %d" % perft(pos, int(tokens[2])))
            else:
                moves = legal_moves(pos)
                if moves:
                    best = min(move_to_uci(m) for m in moves)
                    print("bestmove %s" % best)
                else:
                    print("bestmove 0000")
        elif cmd == "quit":
            break
        sys.stdout.flush()


if __name__ == "__main__":
    main()
