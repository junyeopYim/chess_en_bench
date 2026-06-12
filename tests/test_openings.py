"""Tests for the opening suite loader and its round integration."""

from pathlib import Path

import pytest

from ceb.chess import START_FEN
from ceb.match.internal_runner import play_match
from ceb.match.openings import (
    OpeningError, load_openings_jsonl, opening_start_fen, rotate_suite,
)
from ceb.match.opponents import opponent_command

REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_SUITE = REPO_ROOT / "tracks" / "a_from_scratch" / "public" / "openings_public.jsonl"
EXAMPLE = REPO_ROOT / "examples" / "submissions" / "minimal_uci_engine_python"


def test_public_suite_loads_and_validates():
    suite = load_openings_jsonl(PUBLIC_SUITE)
    assert len(suite) >= 6
    assert suite[0]["id"] == "startpos"
    assert suite[0]["start_fen"] == START_FEN
    fens = {o["start_fen"] for o in suite}
    assert len(fens) == len(suite)  # all openings reach distinct positions


def test_opening_moves_are_applied():
    fen = opening_start_fen(
        {"id": "x", "fen": "startpos", "moves": ["e2e4", "c7c5"]})
    assert fen == "rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq c6 0 2"


def test_illegal_opening_move_fails_loudly():
    with pytest.raises(OpeningError, match="illegal move"):
        opening_start_fen({"id": "bad", "fen": "startpos", "moves": ["e2e5"]})


def test_malformed_rows_fail_loudly(tmp_path):
    bad = tmp_path / "openings.jsonl"
    bad.write_text('{"id": "a", "fen": "startpos", "moves": []}\nnot json\n')
    with pytest.raises(OpeningError, match="bad JSON"):
        load_openings_jsonl(bad)
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n")
    with pytest.raises(OpeningError, match="empty"):
        load_openings_jsonl(empty)
    dup = tmp_path / "dup.jsonl"
    dup.write_text('{"id": "a", "moves": []}\n{"id": "a", "moves": []}\n')
    with pytest.raises(OpeningError, match="duplicate"):
        load_openings_jsonl(dup)


def test_rotate_suite_spreads_coverage():
    suite = [{"id": str(i)} for i in range(6)]
    first = rotate_suite(suite, 2, 0)
    second = rotate_suite(suite, 2, 2)
    wrap = rotate_suite(suite, 2, 5)
    assert [o["id"] for o in first] == ["0", "1"]
    assert [o["id"] for o in second] == ["2", "3"]
    assert [o["id"] for o in wrap] == ["5", "0"]


def test_match_uses_paired_openings_with_color_swap(tmp_path):
    suite = load_openings_jsonl(PUBLIC_SUITE)[:2]
    report = play_match(
        [str(EXAMPLE / "engine")], opponent_command("BenchRandom"),
        games=4, movetime_ms=30, max_plies=16,
        candidate_cwd=str(EXAMPLE), openings=suite,
        games_text_path=tmp_path / "games.txt",
    )
    assert report["openings"] == [o["id"] for o in suite]
    games = report["games"]
    start_fens = {g["start_fen"] for g in games}
    assert len(start_fens) == 2  # two distinct start positions
    # Paired games: same opening, colors swapped.
    assert games[0]["opening_id"] == games[1]["opening_id"]
    assert games[0]["candidate_color"] != games[1]["candidate_color"]
    assert games[2]["opening_id"] == games[3]["opening_id"]
    assert games[2]["opening_id"] != games[0]["opening_id"]


def test_quick_mode_config_selects_multiple_openings():
    from ceb.eval_pack import load_public_pack
    from ceb.rounds.round_runner import (
        DEFAULT_ROUND_MODES, _openings_for_mode)

    pack = load_public_pack(REPO_ROOT)
    quick = _openings_for_mode(pack, DEFAULT_ROUND_MODES["quick"])
    official = _openings_for_mode(pack, DEFAULT_ROUND_MODES["official"])
    assert len(quick) == 2
    assert len(official) == 6
    # The round runner no longer plays everything from START_FEN only.
    assert any(o["start_fen"] != START_FEN for o in official)
