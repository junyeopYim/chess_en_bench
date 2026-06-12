"""Tests for ceb.chess.movegen + perft against canonical CPW node counts."""

import pytest

from ceb.chess import (
    START_FEN, parse_fen, board_to_fen, Move,
    generate_legal, make_move, is_checkmate, is_stalemate, square_index,
)
from ceb.chess.perft import perft

KIWIPETE = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"
CPW_POS3 = "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1"
CPW_POS4 = "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1"
CPW_POS5 = "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8"
CPW_POS6 = "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10"

PERFT_CASES = [
    (START_FEN, 1, 20),
    (START_FEN, 2, 400),
    (START_FEN, 3, 8902),
    (KIWIPETE, 1, 48),
    (KIWIPETE, 2, 2039),
    (KIWIPETE, 3, 97862),
    (CPW_POS3, 1, 14),
    (CPW_POS3, 2, 191),
    (CPW_POS3, 3, 2812),
    (CPW_POS4, 1, 6),
    (CPW_POS4, 2, 264),
    (CPW_POS5, 1, 44),
    (CPW_POS5, 2, 1486),
    (CPW_POS6, 1, 46),
    (CPW_POS6, 2, 2079),
]


@pytest.mark.parametrize("fen,depth,expected", PERFT_CASES)
def test_perft_canonical_counts(fen, depth, expected):
    assert perft(parse_fen(fen), depth) == expected


def test_en_passant_capture_removes_pawn():
    board = parse_fen("rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3")
    after = make_move(board, Move.from_uci("e5f6"))
    assert after.piece_at(square_index("f6")) == "P"
    assert after.piece_at(square_index("f5")) == "."  # captured pawn removed
    assert after.ep_square is None


def test_double_push_sets_ep_square():
    board = parse_fen(START_FEN)
    after = make_move(board, Move.from_uci("e2e4"))
    assert after.ep_square == square_index("e3")


def test_castling_moves_rook_and_clears_rights():
    board = parse_fen("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    legal = {m.uci() for m in generate_legal(board)}
    assert "e1g1" in legal and "e1c1" in legal
    after = make_move(board, Move.from_uci("e1g1"))
    assert after.piece_at(square_index("g1")) == "K"
    assert after.piece_at(square_index("f1")) == "R"
    assert after.piece_at(square_index("h1")) == "."
    assert "K" not in after.castling and "Q" not in after.castling
    assert "k" in after.castling and "q" in after.castling


def test_castling_blocked_through_attacked_square():
    # Black rook on f8 attacks f1: white may not castle kingside.
    board = parse_fen("5rk1/8/8/8/8/8/8/R3K2R w KQ - 0 1")
    legal = {m.uci() for m in generate_legal(board)}
    assert "e1g1" not in legal
    assert "e1c1" in legal


def test_rook_capture_revokes_castling_right():
    board = parse_fen("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    after = make_move(board, Move.from_uci("a1a8"))  # Rxa8
    assert "q" not in after.castling
    assert "k" in after.castling


def test_promotion_generates_four_pieces():
    board = parse_fen("8/P7/8/8/8/8/k6K/8 w - - 0 1")
    promos = sorted(m.uci() for m in generate_legal(board) if m.promotion)
    assert promos == ["a7a8b", "a7a8n", "a7a8q", "a7a8r"]
    after = make_move(board, Move.from_uci("a7a8q"))
    assert after.piece_at(square_index("a8")) == "Q"


def test_fools_mate_is_checkmate():
    board = parse_fen(START_FEN)
    for uci in ("f2f3", "e7e5", "g2g4", "d8h4"):
        board = make_move(board, Move.from_uci(uci))
    assert is_checkmate(board)
    assert not generate_legal(board)


def test_stalemate_detected():
    board = parse_fen("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
    assert is_stalemate(board)
    assert not is_checkmate(board)


def test_pinned_piece_cannot_expose_king():
    # White knight on e4 is pinned by the black rook on e8 (king e1).
    board = parse_fen("4r2k/8/8/8/4N3/8/8/4K3 w - - 0 1")
    knight_moves = [m for m in generate_legal(board)
                    if m.from_sq == square_index("e4")]
    assert knight_moves == []


def test_make_move_does_not_mutate_input():
    board = parse_fen(START_FEN)
    before = board_to_fen(board)
    make_move(board, Move.from_uci("e2e4"))
    assert board_to_fen(board) == before
