"""Tests for hidden-safe error handling (P0.3)."""

import json
from pathlib import Path

import pytest

from ceb.cli import main
from ceb.eval_pack import EvalPackError, resolve_eval_pack
from ceb.match.openings import OpeningError, load_openings_jsonl, opening_start_fen
from ceb.sanitize import sanitize_exception, private_detail

REPO_ROOT = Path(__file__).resolve().parents[1]

SECRET_FEN = "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/5N2/PPPP1PPP/RNBQ1RK1"


def test_hidden_opening_illegal_move_does_not_leak_board():
    row = {"id": "secret_opening", "fen": SECRET_FEN + " b kq - 6 5",
           "moves": ["e8e1"]}  # illegal
    with pytest.raises(OpeningError) as excinfo:
        opening_start_fen(row, hidden=True)
    exc = excinfo.value
    assert "secret_opening" in exc.public_message
    assert "content withheld" in exc.public_message
    assert SECRET_FEN not in exc.public_message
    assert "e8e1" not in exc.public_message
    assert SECRET_FEN in exc.private_message  # operators keep full detail


def test_non_hidden_opening_errors_keep_detail():
    with pytest.raises(OpeningError) as excinfo:
        opening_start_fen({"id": "pub", "fen": "startpos", "moves": ["e2e5"]})
    assert "e2e5" in excinfo.value.public_message  # public data may be quoted


def test_hidden_suite_file_errors_use_basename(tmp_path):
    secret_dir = tmp_path / "very-secret-pack-location"
    secret_dir.mkdir()
    path = secret_dir / "openings_hidden.jsonl"
    path.write_text("not json\n")
    with pytest.raises(OpeningError) as excinfo:
        load_openings_jsonl(path, hidden=True)
    assert "very-secret-pack-location" not in excinfo.value.public_message
    assert "openings_hidden.jsonl" in excinfo.value.public_message


def test_eval_pack_malformed_hidden_opening_does_not_leak(tmp_path):
    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    (pack_dir / "openings_hidden.jsonl").write_text(json.dumps({
        "id": "sneaky", "fen": SECRET_FEN + " b kq - 6 5",
        "moves": ["a7a5", "h2h5"],  # second move illegal
    }) + "\n")
    with pytest.raises((EvalPackError, OpeningError)) as excinfo:
        resolve_eval_pack(REPO_ROOT, private_dir=pack_dir)
    assert SECRET_FEN not in excinfo.value.public_message
    assert "h2h5" not in excinfo.value.public_message


def test_cli_returns_sanitized_error_not_traceback(tmp_path, capsys):
    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    (pack_dir / "fen_hidden.jsonl").write_text(
        '{"id": "secret", "fen": "%s w kq - 6 x"}\n' % SECRET_FEN)
    rc = main(["round", "run", "--track", "A",
               "--workspace", str(REPO_ROOT / "examples" / "submissions" /
                                  "minimal_uci_engine_python"),
               "--round", "1", "--quick", "--eval-pack", str(pack_dir),
               "--runs-dir", str(tmp_path / "runs")])
    out = capsys.readouterr().out
    assert rc != 0
    assert SECRET_FEN not in out
    assert "Traceback" not in out
    assert "secret" in out  # row id is quoted; content is not


def test_cli_unknown_exception_is_withheld(monkeypatch, capsys):
    import ceb.rounds.round_runner as round_runner_module

    def boom(*args, **kwargs):
        raise RuntimeError("SECRET-POSITION %s" % SECRET_FEN)

    monkeypatch.setattr(round_runner_module, "run_round", boom)
    rc = main(["round", "run", "--track", "A", "--workspace", "x",
               "--round", "1", "--quick"])
    out = capsys.readouterr().out
    assert rc == 3
    assert SECRET_FEN not in out
    assert "internal error (RuntimeError)" in out
    assert "Traceback" not in out


def test_sanitize_exception_helpers():
    plain = ValueError("contains %s secret" % SECRET_FEN)
    assert SECRET_FEN not in sanitize_exception(plain)
    assert "ValueError" in sanitize_exception(plain)
    assert SECRET_FEN in private_detail(plain)  # operators see everything

    tagged = EvalPackError("public part", "private part with %s" % SECRET_FEN)
    assert sanitize_exception(tagged) == "public part"
    assert SECRET_FEN in private_detail(tagged)
