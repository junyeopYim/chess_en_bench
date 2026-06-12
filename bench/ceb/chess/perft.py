"""Perft (move-path enumeration) over the oracle movegen."""

from ceb.chess.movegen import generate_legal, make_move


def perft(board, depth):
    """Count leaf nodes of the legal move tree at the given depth."""
    if depth <= 0:
        return 1
    moves = generate_legal(board)
    if depth == 1:
        return len(moves)
    total = 0
    for move in moves:
        total += perft(make_move(board, move), depth - 1)
    return total


def perft_divide(board, depth):
    """Per-root-move node counts: {uci_move: count}. Debugging aid."""
    result = {}
    for move in generate_legal(board):
        result[move.uci()] = perft(make_move(board, move), depth - 1) if depth > 1 else 1
    return result
