"""Tests for the trusted official eval-pack policy (v0.3.2, section A)."""

import json
from pathlib import Path

import pytest

from ceb.hosted.eval_pack_trust import (
    EvalPackTrustError, compute_eval_pack_hash, load_eval_pack_manifest,
    resolve_allowed_hashes, validate_official_eval_pack)

from conftest import make_official_pack

REPO_ROOT = Path(__file__).resolve().parents[1]
TINY_PACK = REPO_ROOT / "examples" / "eval_packs" / "tiny_private"


def test_official_pack_validates_and_reports_hashes(official_pack):
    report = validate_official_eval_pack(official_pack, track="A")
    assert report["trusted"] is True
    assert report["pack_id"] == "ceb-test-2026s1"
    assert report["pack_hash"].startswith("sha256:")
    assert report["manifest_hash"].startswith("sha256:")
    assert report["track"] == "BOTH"
    assert report["season"] == "2026-s1"
    # Hash is deterministic.
    assert report["pack_hash"] == compute_eval_pack_hash(official_pack)


def test_demo_pack_cannot_be_official():
    # The committed demo pack lacks an official manifest -> rejected.
    with pytest.raises(EvalPackTrustError, match="manifest schema"):
        validate_official_eval_pack(TINY_PACK, track="A")


def test_committed_demo_path_rejected_even_with_manifest(tmp_path, monkeypatch):
    # A pack with a valid manifest but living under the repo's examples/ is
    # still rejected (unless an explicit dev flag is set).
    fake_examples = REPO_ROOT / "examples" / "_trust_probe_pack"
    try:
        make_official_pack(fake_examples)
        with pytest.raises(EvalPackTrustError, match="committed/demo path"):
            validate_official_eval_pack(fake_examples, track="A")
        # allow_demo bypasses the path check (still needs the official manifest).
        report = validate_official_eval_pack(fake_examples, track="A",
                                             allow_demo=True)
        assert report["trusted"] is True
    finally:
        import shutil
        shutil.rmtree(fake_examples, ignore_errors=True)


def test_allowlist_must_match(official_pack):
    good = compute_eval_pack_hash(official_pack)
    assert validate_official_eval_pack(
        official_pack, track="A", allowed_hashes=[good])["allowlist_checked"]
    with pytest.raises(EvalPackTrustError, match="allowlist"):
        validate_official_eval_pack(official_pack, track="A",
                                    allowed_hashes=["sha256:deadbeef"])


def test_track_mismatch_rejected(tmp_path):
    pack = make_official_pack(tmp_path / "a_only", manifest_overrides={"track": "A"})
    assert validate_official_eval_pack(pack, track="A")["track"] == "A"
    with pytest.raises(EvalPackTrustError, match="track"):
        validate_official_eval_pack(pack, track="B")


def test_missing_required_keys_rejected(tmp_path):
    pack = make_official_pack(tmp_path / "p")
    manifest = json.loads((pack / "manifest.json").read_text())
    del manifest["pack_id"]
    (pack / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(EvalPackTrustError, match="missing required keys"):
        validate_official_eval_pack(pack, track="A")


def test_official_false_rejected(tmp_path):
    pack = make_official_pack(tmp_path / "p", manifest_overrides={"official": False})
    with pytest.raises(EvalPackTrustError, match="official"):
        validate_official_eval_pack(pack, track="A")


def test_resolve_allowed_hashes_merges_sources(tmp_path, monkeypatch):
    monkeypatch.setenv("CEB_OFFICIAL_EVAL_PACK_HASHES", "sha256:env1, sha256:env2")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"hashes": ["sha256:reg1"]}))
    out = resolve_allowed_hashes(cli_hashes=["sha256:cli1,sha256:cli2"],
                                 registry_path=registry)
    assert out == {"sha256:env1", "sha256:env2", "sha256:cli1", "sha256:cli2",
                   "sha256:reg1"}


def test_manifest_must_exist(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(EvalPackTrustError, match="manifest"):
        load_eval_pack_manifest(tmp_path / "empty")
