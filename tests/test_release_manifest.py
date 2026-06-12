"""Tests for the public release manifest (v0.3.3, req 9)."""

import json
from pathlib import Path

import pytest

from ceb.hosted.eval_pack_trust import compute_eval_pack_hash
from ceb.hosted.release_manifest import (
    build_release_manifest, ReleaseManifestError)
from ceb.hosted.signing import generate_keypair, load_public_key, \
    public_key_fingerprint

REPO_ROOT = Path(__file__).resolve().parents[1]
TINY_PACK = REPO_ROOT / "examples" / "eval_packs" / "tiny_private"


def _pub(tmp_path):
    generate_keypair(tmp_path / "priv.pem", tmp_path / "pub.pem")
    return str(tmp_path / "pub.pem")


def test_release_manifest_track_a(tmp_path, official_pack):
    pub = _pub(tmp_path)
    pack_hash = compute_eval_pack_hash(official_pack)
    m = build_release_manifest(
        track="A", eval_pack_dir=str(official_pack), public_key_path=pub,
        official_pack_hashes=[pack_hash], root=REPO_ROOT)
    assert m["schema"] == "ceb.release_manifest/v1"
    assert m["track"] == "A"
    assert m["official_eval_pack_hash"] == pack_hash
    assert m["official_eval_pack_id"] == "ceb-test-2026s1"
    assert m["operator_public_key_fingerprint"] == \
        public_key_fingerprint(load_public_key(pub))
    assert m["engine_jail_image"].startswith("chess-en-bench-jail")
    assert isinstance(m["known_limitations"], list) and m["known_limitations"]
    assert "single-node" in " ".join(m["known_limitations"])
    # No secrets: no key material or private paths in the manifest values.
    blob = json.dumps(m)
    assert "PRIVATE" not in blob and "priv.pem" not in blob
    assert "BEGIN" not in blob


def test_release_manifest_requires_pin(tmp_path, official_pack):
    pub = _pub(tmp_path)
    with pytest.raises(ReleaseManifestError, match="pinned"):
        build_release_manifest(track="A", eval_pack_dir=str(official_pack),
                               public_key_path=pub, root=REPO_ROOT)


def test_release_manifest_rejects_demo_pack(tmp_path):
    pub = _pub(tmp_path)
    with pytest.raises(ReleaseManifestError, match="eval pack"):
        build_release_manifest(
            track="A", eval_pack_dir=str(TINY_PACK), public_key_path=pub,
            official_pack_hashes=[compute_eval_pack_hash(TINY_PACK)],
            root=REPO_ROOT)


def test_release_manifest_track_b_requires_baseline_and_wrapper(tmp_path,
                                                                official_pack):
    pub = _pub(tmp_path)
    pack_hash = compute_eval_pack_hash(official_pack)
    with pytest.raises(ReleaseManifestError, match="baseline"):
        build_release_manifest(
            track="B", eval_pack_dir=str(official_pack), public_key_path=pub,
            official_pack_hashes=[pack_hash], root=REPO_ROOT)
    m = build_release_manifest(
        track="B", eval_pack_dir=str(official_pack), public_key_path=pub,
        official_pack_hashes=[pack_hash],
        track_b_baseline_hashes=["sha256:" + "1" * 64],
        build_wrapper_hashes=["sha256:" + "2" * 64], root=REPO_ROOT)
    assert m["track"] == "B"
    assert m["track_b_baseline_hash"] == "sha256:" + "1" * 64
    assert m["track_b_build_wrapper_hash"] == "sha256:" + "2" * 64


def test_release_manifest_cli(tmp_path, official_pack, capsys):
    from ceb.cli import main
    pub = _pub(tmp_path)
    out = tmp_path / "rel.json"
    rc = main(["hosted", "release-manifest", "create", "--track", "A",
               "--eval-pack", str(official_pack), "--public-key", pub,
               "--official-pack-hash", compute_eval_pack_hash(official_pack),
               "--out", str(out)])
    assert rc == 0
    m = json.loads(out.read_text())
    assert m["schema"] == "ceb.release_manifest/v1"


def test_release_manifest_track_b_ambiguous_hash(tmp_path, official_pack):
    pub = _pub(tmp_path)
    with pytest.raises(ReleaseManifestError, match="multiple|exactly one"):
        build_release_manifest(
            track="B", eval_pack_dir=str(official_pack), public_key_path=pub,
            official_pack_hashes=[compute_eval_pack_hash(official_pack)],
            track_b_baseline_hashes=["sha256:" + "1" * 64, "sha256:" + "2" * 64],
            build_wrapper_hashes=["sha256:" + "3" * 64], root=REPO_ROOT)
