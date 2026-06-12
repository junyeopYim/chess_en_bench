"""Tests for ceb.chess.fen (parse/generate round-trips and validation)."""

import pytest

from ceb.chess import START_FEN, parse_fen, board_to_fen, square_index

ROUNDTRIP_FENS = [
    START_FEN,
    "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    "rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3",
    "8/P7/8/8/8/8/k6K/8 w - - 0 1",
    "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
    "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
]


@pytest.mark.parametrize("fen", ROUNDTRIP_FENS)
def test_fen_roundtrip(fen):
    assert board_to_fen(parse_fen(fen)) == fen


def test_startpos_fields():
    board = parse_fen(START_FEN)
    assert board.side_to_move == "w"
    assert board.castling == "KQkq"
    assert board.ep_square is None
    assert board.halfmove_clock == 0
    assert board.fullmove_number == 1
    assert board.piece_at(square_index("e1")) == "K"
    assert board.piece_at(square_index("e8")) == "k"
    assert board.piece_at(square_index("a1")) == "R"
    assert board.piece_at(square_index("d8")) == "q"


def test_ep_square_parsed():
    board = parse_fen("rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3")
    assert board.ep_square == square_index("f6")


def test_four_field_fen_defaults_counters():
    board = parse_fen("8/P7/8/8/8/8/k6K/8 w - -")
    assert board.halfmove_clock == 0
    assert board.fullmove_number == 1


def test_castling_normalized_order():
    board = parse_fen("r3k2r/8/8/8/8/8/8/R3K2R w qkQK - 0 1")
    assert board.castling == "KQkq"


@pytest.mark.parametrize("bad_fen", [
    "",                                                       # empty
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP w KQkq - 0 1",        # 7 ranks
    "rnbqkbnr/pppppppp/9/8/8/8/8/PPPPPPPP w KQkq - 0 1",      # rank overflow
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQXBNR w KQkq - 0 1",  # bad piece
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR x KQkq - 0 1",  # bad side
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KX - 0 1",    # bad castling
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq e5 0 1", # ep rank
    "8/8/8/8/8/8/8/8 w - - 0 1",                              # no kings
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - -1 1", # bad clock
])
def test_invalid_fens_raise(bad_fen):
    with pytest.raises(ValueError):
        parse_fen(bad_fen)
