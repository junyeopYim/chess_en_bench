"""Tests for eval pack loading and hidden-data sanitization."""

import json
from pathlib import Path

import pytest

from ceb.eval_pack import (
    EvalPackError, load_public_pack, resolve_eval_pack, ENV_PRIVATE_DIR,
)
from ceb.rounds.feedback import make_feedback
from ceb.scoring.track_a import compute_round_score

REPO_ROOT = Path(__file__).resolve().parents[1]
TINY_PACK = REPO_ROOT / "examples" / "eval_packs" / "tiny_private"

HIDDEN_FENS = [
    "8/8/8/3k4/8/8/4Q3/4K3",       # placement of tiny_kq_endgame
    "8/8/8/8/2k5/8/2K1R3/8",       # placement of tiny_rook_endgame
]
HIDDEN_OPENING_MOVES = ["d7d5", "d7d6"]  # signature moves of hidden openings


def test_public_pack_loads():
    pack = load_public_pack(REPO_ROOT)
    assert pack.source == "public"
    assert len(pack.fens) >= 10
    assert len(pack.perft) >= 10
    assert len(pack.openings) >= 6


def test_private_pack_extends_public():
    public = load_public_pack(REPO_ROOT)
    merged = resolve_eval_pack(REPO_ROOT, private_dir=TINY_PACK)
    assert merged.source == "public+private"
    assert merged.name == "tiny_private_example"
    assert len(merged.fens) == len(public.fens) + 2
    assert len(merged.perft) == len(public.perft) + 2
    # manifest says openings_mode=extend
    assert len(merged.openings) == len(public.openings) + 2
    assert {o["id"] for o in merged.openings} >= {"hidden_scandinavian",
                                                  "hidden_pirc"}


def test_replace_mode_overrides_openings(tmp_path):
    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    (pack_dir / "openings_hidden.jsonl").write_text(
        '{"id": "only_one", "fen": "startpos", "moves": ["e2e4"]}\n')
    (pack_dir / "manifest.json").write_text(
        '{"name": "replacer", "openings_mode": "replace"}\n')
    pack = resolve_eval_pack(REPO_ROOT, private_dir=pack_dir)
    assert [o["id"] for o in pack.openings] == ["only_one"]


def test_missing_or_empty_pack_dir_errors(tmp_path):
    with pytest.raises(EvalPackError, match="not found"):
        resolve_eval_pack(REPO_ROOT, private_dir=tmp_path / "nope")
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(EvalPackError, match="contains none of"):
        resolve_eval_pack(REPO_ROOT, private_dir=empty)


def test_env_var_only_used_when_allowed(monkeypatch):
    monkeypatch.setenv(ENV_PRIVATE_DIR, str(TINY_PACK))
    public_only = resolve_eval_pack(REPO_ROOT, allow_env=False)
    assert public_only.source == "public"
    official = resolve_eval_pack(REPO_ROOT, allow_env=True)
    assert official.source == "public+private"


def test_invalid_hidden_fen_rejected_without_leaking(tmp_path):
    """A typo'd hidden FEN must fail at load time and the error must not
    contain the position itself."""
    secret_placement = "2r3k1/5ppp/8/8/8/8/5PPP/2R3K1"
    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    (pack_dir / "fen_hidden.jsonl").write_text(
        '{"id": "secret", "fen": "%s w - - 0 x"}\n' % secret_placement)
    with pytest.raises(EvalPackError) as excinfo:
        resolve_eval_pack(REPO_ROOT, private_dir=pack_dir)
    message = str(excinfo.value)
    assert "secret" in message          # the row id is quoted...
    assert secret_placement not in message  # ...the position never is


def test_manifest_must_be_a_json_object(tmp_path):
    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    (pack_dir / "openings_hidden.jsonl").write_text(
        '{"id": "x", "fen": "startpos", "moves": ["e2e4"]}\n')
    (pack_dir / "manifest.json").write_text('"just a string"\n')
    with pytest.raises(EvalPackError, match="JSON object"):
        resolve_eval_pack(REPO_ROOT, private_dir=pack_dir)


def test_private_rows_always_have_ids(tmp_path):
    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    (pack_dir / "fen_hidden.jsonl").write_text(
        '{"fen": "8/8/8/3k4/8/8/4Q3/4K3 w - - 0 1"}\n')
    pack = resolve_eval_pack(REPO_ROOT, private_dir=pack_dir)
    assert all(row.get("id") for row in pack.fens)


def test_official_round_with_tiny_private_pack(tmp_path):
    """An official round can consume a hidden opening pack, and nothing
    hidden leaks into the agent-facing feedback."""
    import shutil
    from ceb.rounds.round_runner import run_round

    # Replace-mode pack: the round plays ONLY the hidden openings.
    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    for name in ("fen_hidden.jsonl", "perft_hidden.jsonl",
                 "openings_hidden.jsonl"):
        shutil.copy(TINY_PACK / name, pack_dir / name)
    (pack_dir / "manifest.json").write_text(
        '{"name": "tiny_replace", "openings_mode": "replace"}\n')

    example = REPO_ROOT / "examples" / "submissions" / "minimal_uci_engine_python"
    runs_root = tmp_path / "runs"
    report, feedback, state = run_round(
        example, 1, quick=False, run_id="tiny_official", runs_root=runs_root,
        eval_pack_dir=pack_dir,
        mode_config={"opponents": ["BenchRandom"], "games_per_opponent": 2,
                     "movetime_ms": 30, "max_plies": 30, "openings_limit": 1})

    assert report["mode"] == "official"
    assert report["strict_gate"] is True
    assert report["eval_pack"]["source"] == "public+private"
    assert report["openings_used"] == ["hidden_scandinavian"]
    assert state.budget_used == 1

    # Sanitization: hidden FENs/moves/ids never reach the feedback.
    text = json.dumps(feedback)
    scandinavian_fen = "rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR"
    assert scandinavian_fen not in text
    assert "hidden_scandinavian" not in text
    for fen in HIDDEN_FENS:
        assert fen not in text


def test_feedback_does_not_leak_hidden_data():
    # Build a round score from matches that used hidden openings, then make
    # sure the agent-facing feedback never quotes hidden FENs or moves.
    match_report = {
        "opponent": "BenchRandom",
        "openings": ["hidden_scandinavian", "hidden_pirc"],
        "totals": {"wins": 1, "draws": 1, "losses": 0},
        "candidate_faults": {"illegal": 0, "timeout": 0, "crash": 0},
    }
    score = compute_round_score([match_report])
    round_report = {
        "schema": "ceb.round.report/v1", "run_id": "x", "track": "A",
        "round": 1, "mode": "official", "score": score,
    }
    feedback = json.dumps(make_feedback(round_report))
    for fen in HIDDEN_FENS:
        assert fen not in feedback
    for move in HIDDEN_OPENING_MOVES:
        assert '"%s"' % move not in feedback
    assert "hidden_scandinavian" not in feedback  # not even opening ids
