"""Benchmark-owned UCI opponents for Track A.

Run one as a UCI engine subprocess:

    python -m ceb.match.opponents BenchRandom

All opponents share one engine shell and differ only in move selection.
They are deterministic given a seed (set via `setoption name Seed value N`;
the internal match runner seeds each game for reproducibility).
"""

import random
import sys
import time

from ceb.chess import (
    Board, START_FEN, parse_fen, Move,
    generate_legal, make_move, in_check,
)
from ceb.chess.perft import perft

MATE_SCORE = 100_000

PIECE_VALUES = {"P": 100, "N": 320, "B": 330, "R": 500, "Q": 900, "K": 0}

# Small center-weighted bonus table indexed by square (a1=0..h8=63),
# symmetric so it serves both colors after mirroring.
_FILE_BONUS = (0, 1, 2, 3, 3, 2, 1, 0)
_RANK_BONUS = (0, 1, 2, 3, 3, 2, 1, 0)
PST_CENTER = [4 * (_FILE_BONUS[s % 8] + _RANK_BONUS[s // 8]) for s in range(64)]
# Pawns additionally like advancing.
PST_PAWN_ADVANCE_WHITE = [3 * (s // 8) for s in range(64)]
PST_PAWN_ADVANCE_BLACK = [3 * (7 - s // 8) for s in range(64)]


class SearchTimeout(Exception):
    pass


def evaluate(board, use_pst):
    """Static eval in centipawns from White's perspective."""
    score = 0
    for sq, piece in enumerate(board.squares):
        if piece == ".":
            continue
        value = PIECE_VALUES[piece.upper()]
        if use_pst:
            value += PST_CENTER[sq]
            if piece == "P":
                value += PST_PAWN_ADVANCE_WHITE[sq]
            elif piece == "p":
                value += PST_PAWN_ADVANCE_BLACK[sq]
        score += value if piece.isupper() else -value
    return score


def _eval_stm(board, use_pst):
    """Static eval from the side-to-move's perspective."""
    score = evaluate(board, use_pst)
    return score if board.white_to_move() else -score


def _negamax(board, depth, alpha, beta, use_pst, deadline):
    if time.monotonic() > deadline:
        raise SearchTimeout()
    moves = generate_legal(board)
    if not moves:
        return -MATE_SCORE if in_check(board) else 0
    if depth <= 0:
        return _eval_stm(board, use_pst)
    best = -MATE_SCORE - 1
    for move in moves:
        value = -_negamax(make_move(board, move), depth - 1,
                          -beta, -alpha, use_pst, deadline)
        if value > best:
            best = value
        if best > alpha:
            alpha = best
        if alpha >= beta:
            break
    return best


def _search_root(board, depth, use_pst, deadline, rng):
    """Best moves at fixed depth (list of equally-scored top moves)."""
    moves = generate_legal(board)
    best_score = None
    best_moves = []
    for move in moves:
        value = -_negamax(make_move(board, move), depth - 1,
                          -MATE_SCORE - 1, MATE_SCORE + 1, use_pst, deadline)
        if best_score is None or value > best_score:
            best_score = value
            best_moves = [move]
        elif value == best_score:
            best_moves.append(move)
    return best_moves


def _choose_depth_based(board, max_depth, use_pst, movetime_ms, rng):
    """Iterative deepening capped at max_depth; falls back to the deepest
    completed iteration when time runs out."""
    legal = generate_legal(board)
    if not legal:
        return None
    choice = rng.choice(legal)
    budget_s = max(movetime_ms, 10) / 1000.0
    deadline = time.monotonic() + max(budget_s * 0.8, 0.01)
    for depth in range(1, max_depth + 1):
        try:
            candidates = _search_root(board, depth, use_pst, deadline, rng)
        except SearchTimeout:
            break
        if candidates:
            choice = rng.choice(candidates)
    return choice


def _choose_random(board, movetime_ms, rng):
    legal = generate_legal(board)
    return rng.choice(legal) if legal else None


def _choose_greedy_capture(board, movetime_ms, rng):
    legal = generate_legal(board)
    if not legal:
        return None
    captures = []
    for move in legal:
        victim = board.piece_at(move.to_sq)
        if victim != ".":
            captures.append((PIECE_VALUES[victim.upper()], move))
        elif board.ep_square is not None and move.to_sq == board.ep_square \
                and board.piece_at(move.from_sq) in "Pp":
            captures.append((PIECE_VALUES["P"], move))
    if captures:
        best = max(v for v, _ in captures)
        return rng.choice([m for v, m in captures if v == best])
    return rng.choice(legal)


STRATEGIES = {
    "BenchRandom": lambda b, mt, rng: _choose_random(b, mt, rng),
    "BenchGreedyCapture": lambda b, mt, rng: _choose_greedy_capture(b, mt, rng),
    "BenchMaterial1": lambda b, mt, rng: _choose_depth_based(b, 1, False, mt, rng),
    "BenchPST1": lambda b, mt, rng: _choose_depth_based(b, 1, True, mt, rng),
    "BenchMiniMax2": lambda b, mt, rng: _choose_depth_based(b, 2, False, mt, rng),
    "BenchAlphaBeta3": lambda b, mt, rng: _choose_depth_based(b, 3, True, mt, rng),
}

OPPONENT_NAMES = list(STRATEGIES)


def opponent_command(name):
    """argv to launch a benchmark opponent as a UCI subprocess."""
    if name not in STRATEGIES:
        raise ValueError("unknown opponent %r (have: %s)" % (name, ", ".join(STRATEGIES)))
    return [sys.executable, "-m", "ceb.match.opponents", name]


# ----- UCI shell -------------------------------------------------------------

def _parse_position(tokens):
    """tokens after 'position' -> Board."""
    board = parse_fen(START_FEN)
    idx = 0
    if tokens and tokens[0] == "startpos":
        idx = 1
    elif tokens and tokens[0] == "fen":
        end = len(tokens)
        for i, tok in enumerate(tokens):
            if tok == "moves":
                end = i
                break
        board = parse_fen(" ".join(tokens[1:end]))
        idx = end
    if idx < len(tokens) and tokens[idx] == "moves":
        for mv in tokens[idx + 1:]:
            board = make_move(board, Move.from_uci(mv))
    return board


def _parse_go_movetime(tokens):
    movetime = 1000
    for i, tok in enumerate(tokens):
        if tok == "movetime" and i + 1 < len(tokens):
            try:
                movetime = int(tokens[i + 1])
            except ValueError:
                pass
    return movetime


def uci_loop(name, stdin=None, stdout=None):
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    strategy = STRATEGIES[name]
    rng = random.Random(0xCEB)
    board = parse_fen(START_FEN)

    def emit(line):
        stdout.write(line + "\n")
        stdout.flush()

    for raw in stdin:
        tokens = raw.split()
        if not tokens:
            continue
        cmd = tokens[0]
        if cmd == "uci":
            emit("id name %s (chess_en_bench opponent)" % name)
            emit("id author chess_en_bench")
            emit("option name Seed type spin default %d min 0 max 999999999" % 0xCEB)
            emit("uciok")
        elif cmd == "isready":
            emit("readyok")
        elif cmd == "ucinewgame":
            board = parse_fen(START_FEN)
        elif cmd == "setoption":
            # setoption name Seed value N
            lowered = [t.lower() for t in tokens]
            if "name" in lowered and "value" in lowered:
                try:
                    name_idx = lowered.index("name")
                    value_idx = lowered.index("value")
                    opt = " ".join(tokens[name_idx + 1:value_idx]).lower()
                    if opt == "seed":
                        rng = random.Random(int(tokens[value_idx + 1]))
                except (ValueError, IndexError):
                    pass
        elif cmd == "position":
            try:
                board = _parse_position(tokens[1:])
            except (ValueError, IndexError):
                pass  # keep previous position; GUI error
        elif cmd == "go":
            if len(tokens) >= 2 and tokens[1] == "perft":
                try:
                    depth = int(tokens[2])
                except (ValueError, IndexError):
                    depth = 1
                emit("info string perft %d" % perft(board, depth))
                continue
            movetime = _parse_go_movetime(tokens[1:])
            move = strategy(board, movetime, rng)
            emit("bestmove %s" % (move.uci() if move else "0000"))
        elif cmd == "quit":
            break


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in STRATEGIES:
        sys.stderr.write("usage: python -m ceb.match.opponents <%s>\n"
                         % "|".join(STRATEGIES))
        return 2
    uci_loop(argv[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
