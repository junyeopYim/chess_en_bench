"""Tests for the artifact visibility model and hidden-data leak scanning (P0.2)."""

import json
import shutil
from pathlib import Path

import pytest

from ceb.rounds.round_runner import run_round
from ceb.storage import (
    VISIBILITY_PRIVATE, VISIBILITY_PUBLIC, public_artifacts, read_manifest,
    visibility_of, write_artifact,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples" / "submissions" / "minimal_uci_engine_python"
TINY_PACK = REPO_ROOT / "examples" / "eval_packs" / "tiny_private"

# Secret strings from the tiny pack that must never reach public artifacts.
TINY_SECRETS = [
    "8/8/8/3k4/8/8/4Q3/4K3",      # fen_hidden row 1 placement
    "8/8/8/8/2k5/8/2K1R3/8",      # fen_hidden row 2 placement
    "hidden_scandinavian",         # hidden opening id
    "hidden_pirc",                 # hidden opening id
    "tiny_kq_endgame",             # hidden row id (ids stay out of artifacts)
]


def test_manifest_tracks_visibility(tmp_path):
    write_artifact(tmp_path, "pub.json", {"x": 1}, VISIBILITY_PUBLIC)
    write_artifact(tmp_path, "priv.json", {"y": 2}, VISIBILITY_PRIVATE)
    assert public_artifacts(tmp_path) == ["pub.json"]
    assert visibility_of(tmp_path, "priv.json") == VISIBILITY_PRIVATE
    assert visibility_of(tmp_path, "unlisted.json") is None  # deny by default
    manifest = read_manifest(tmp_path)
    assert manifest["artifacts"]["priv.json"]["visibility"] == "private"


@pytest.fixture(scope="module")
def private_round(tmp_path_factory):
    """An official round played entirely on hidden openings."""
    base = tmp_path_factory.mktemp("vis")
    pack_dir = base / "pack"
    pack_dir.mkdir()
    for name in ("fen_hidden.jsonl", "perft_hidden.jsonl",
                 "openings_hidden.jsonl"):
        shutil.copy(TINY_PACK / name, pack_dir / name)
    (pack_dir / "manifest.json").write_text(
        '{"name": "tiny_replace", "openings_mode": "replace"}\n')
    runs_root = base / "runs"
    report, feedback, state = run_round(
        EXAMPLE, 1, quick=False, run_id="vis_test", runs_root=runs_root,
        eval_pack_dir=pack_dir,
        mode_config={"opponents": ["BenchRandom"], "games_per_opponent": 2,
                     "movetime_ms": 30, "max_plies": 30, "openings_limit": 1})
    return runs_root / "vis_test" / "round_1"


def test_round_artifacts_have_correct_visibility(private_round):
    public = set(public_artifacts(private_round))
    assert public == {"feedback.json", "report.public.json"}
    assert visibility_of(private_round, "report.json") == VISIBILITY_PRIVATE
    assert visibility_of(private_round, "match_vs_BenchRandom.json") == \
        VISIBILITY_PRIVATE
    assert visibility_of(private_round, "games_vs_BenchRandom.txt") == \
        VISIBILITY_PRIVATE


def test_public_artifacts_leak_scan(private_round):
    """Leak scanner: no secret from the private pack may appear in any
    public artifact."""
    for name in public_artifacts(private_round):
        text = (private_round / name).read_text()
        for secret in TINY_SECRETS:
            assert secret not in text, "%s leaked into %s" % (secret, name)
        # Host paths are private too.
        assert str(REPO_ROOT) not in text


def test_private_artifacts_keep_detail_but_are_marked(private_round):
    report = json.loads((private_round / "report.json").read_text())
    assert report["openings_used"] == ["hidden_scandinavian"]  # full detail
    assert visibility_of(private_round, "report.json") == VISIBILITY_PRIVATE
    match = json.loads((private_round / "match_vs_BenchRandom.json").read_text())
    assert match["games"][0]["start_fen"]  # private artifacts may hold FENs


def test_public_report_shape(private_round):
    public_report = json.loads((private_round / "report.public.json").read_text())
    assert public_report["schema"] == "ceb.round.report.public/v1"
    assert public_report["mode"] == "official_round"
    assert public_report["verified"] is False  # self-reported
    coverage = public_report["opening_coverage"]
    assert coverage["openings_played"] == 1
    assert coverage["opening_ids"] is None  # hidden pack: ids withheld
    assert "workspace" not in public_report  # host paths withheld


def test_public_opening_ids_visible_for_public_pack(tmp_path):
    report, feedback, state = run_round(
        EXAMPLE, 1, quick=True, run_id="pub_vis", runs_root=tmp_path)
    public_report = json.loads(
        (tmp_path / "pub_vis" / "round_1" / "report.public.json").read_text())
    assert public_report["opening_coverage"]["opening_ids"]  # public ids ok
