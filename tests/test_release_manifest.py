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


def test_release_manifest_track_b_has_bench_policy_and_trust_mode(tmp_path,
                                                                  official_pack):
    pub = _pub(tmp_path)
    m = build_release_manifest(
        track="B", eval_pack_dir=str(official_pack), public_key_path=pub,
        official_pack_hashes=[compute_eval_pack_hash(official_pack)],
        track_b_baseline_hashes=["sha256:" + "1" * 64],
        build_wrapper_hashes=["sha256:" + "2" * 64], root=REPO_ROOT)
    assert m["track_b_baseline_trust_mode"] == "hash"
    assert m["bench_policy"]["override_downgrades_to_diagnostic"] is True
    assert m["bench_policy"]["supported_required_for_verified"] is True
    assert m["official_eval_pack_manifest_hash"].startswith("sha256:")


# ----- v0.3.5: signed release manifests (req 3) -------------------------------

def _manifest(tmp_path, official_pack):
    pub = _pub(tmp_path)
    return build_release_manifest(
        track="A", eval_pack_dir=str(official_pack), public_key_path=pub,
        official_pack_hashes=[compute_eval_pack_hash(official_pack)],
        root=REPO_ROOT), pub


def test_signed_manifest_verifies_with_matching_public_key(tmp_path, official_pack):
    from ceb.hosted.release_manifest import (
        sign_release_manifest, verify_release_manifest)
    from ceb.hosted.signing import load_public_key
    m, pub = _manifest(tmp_path, official_pack)
    sign_release_manifest(m, private_key_path=str(tmp_path / "priv.pem"))
    assert m["signature"]["algorithm"] == "ed25519"
    # Authentic only against the out-of-band public key.
    verdict = verify_release_manifest(m, public_key=load_public_key(pub))
    assert verdict["signed"] is True and verdict["authentic"] is True
    assert verdict["signature_trust"] == "supplied-public-key"
    # Embedded-only verification proves consistency, NOT authenticity.
    embedded = verify_release_manifest(m)
    assert embedded["signature_ok"] is True and embedded["authentic"] is False


def test_modified_signed_manifest_fails_verification(tmp_path, official_pack):
    from ceb.hosted.release_manifest import (
        sign_release_manifest, verify_release_manifest)
    from ceb.hosted.signing import load_public_key
    m, pub = _manifest(tmp_path, official_pack)
    sign_release_manifest(m, private_key_path=str(tmp_path / "priv.pem"))
    m["official_eval_pack_hash"] = "sha256:" + "0" * 64   # tamper
    verdict = verify_release_manifest(m, public_key=load_public_key(pub))
    assert verdict["signature_ok"] is False and verdict["authentic"] is False


def test_unsigned_manifest_readable_but_not_authentic(tmp_path, official_pack):
    from ceb.hosted.release_manifest import verify_release_manifest
    m, _ = _manifest(tmp_path, official_pack)
    verdict = verify_release_manifest(m)   # never signed
    assert verdict["signed"] is False and verdict["authentic"] is False
    assert m["official_eval_pack_hash"]    # still fully readable


def test_release_manifest_create_signs_with_private_key(tmp_path, official_pack):
    from ceb.cli import main
    from ceb.hosted.verifier import verify_release_manifest_file
    from ceb.hosted.signing import load_public_key, generate_keypair
    generate_keypair(tmp_path / "p.pem", tmp_path / "pub.pem")
    out = tmp_path / "rel.json"
    rc = main(["hosted", "release-manifest", "create", "--track", "A",
               "--eval-pack", str(official_pack), "--public-key",
               str(tmp_path / "pub.pem"),
               "--official-pack-hash", compute_eval_pack_hash(official_pack),
               "--private-key", str(tmp_path / "p.pem"), "--out", str(out)])
    assert rc == 0
    m = json.loads(out.read_text())
    assert m["signature"]["algorithm"] == "ed25519"
    verdict = verify_release_manifest_file(
        out, public_key=load_public_key(tmp_path / "pub.pem"))
    assert verdict["authentic"] is True


def test_release_manifest_sign_verify_cli_roundtrip(tmp_path, official_pack, capsys):
    from ceb.cli import main
    from ceb.hosted.signing import generate_keypair
    generate_keypair(tmp_path / "p.pem", tmp_path / "pub.pem")
    out = tmp_path / "rel.json"
    # Create unsigned, then sign, then verify (exit 0 only with the public key).
    main(["hosted", "release-manifest", "create", "--track", "A",
          "--eval-pack", str(official_pack), "--public-key", str(tmp_path / "pub.pem"),
          "--official-pack-hash", compute_eval_pack_hash(official_pack),
          "--out", str(out)])
    assert "signature" not in json.loads(out.read_text())
    assert main(["hosted", "release-manifest", "sign", "--manifest", str(out),
                 "--private-key", str(tmp_path / "p.pem")]) == 0
    # Without the public key: not authentic (exit 2). With it: authentic (exit 0).
    assert main(["hosted", "release-manifest", "verify", "--manifest", str(out)]) == 2
    assert main(["hosted", "release-manifest", "verify", "--manifest", str(out),
                 "--public-key", str(tmp_path / "pub.pem")]) == 0


# ----- v0.3.5: public-official release checklist (req 4) ----------------------

def test_release_checklist_renders_commit_safe_markdown(tmp_path, official_pack):
    from ceb.hosted.release_checklist import build_release_checklist
    from ceb.hosted.readiness import readiness_declare
    from ceb.hosted.signing import generate_keypair
    import ceb.jail.docker_engine as de
    import ceb.hosted.readiness as rmod
    from ceb.hosted import db as hosted_db

    generate_keypair(tmp_path / "priv.pem", tmp_path / "pub.pem")
    # A signed manifest + a ready declaration report.
    pub = _pub(tmp_path)
    rel = build_release_manifest(
        track="A", eval_pack_dir=str(official_pack), public_key_path=pub,
        official_pack_hashes=[compute_eval_pack_hash(official_pack)], root=REPO_ROOT)
    rel_path = tmp_path / "release.json"
    rel_path.write_text(json.dumps(rel))

    import unittest.mock as mock
    with mock.patch.object(de, "docker_available", lambda: True), \
         mock.patch.object(rmod, "_image_present", lambda image: True):
        report = readiness_declare(
            db_path=str(hosted_db.init_db(tmp_path / "h.sqlite")),
            eval_pack_dir=str(official_pack),
            public_key_path=str(tmp_path / "pub.pem"),
            signing_key_path=str(tmp_path / "priv.pem"), track="A",
            official_pack_hashes=[compute_eval_pack_hash(official_pack)],
            release_manifest=str(rel_path))
    report_path = tmp_path / "readiness.json"
    report_path.write_text(json.dumps(report))

    text = build_release_checklist(
        track="A", readiness_report=str(report_path),
        release_manifest=str(rel_path))
    assert "public-official release checklist" in text
    assert rel["official_eval_pack_hash"] in text
    assert rel["operator_public_key_fingerprint"] in text
    assert "Do NOT declare" in text
    assert "ready" in text
    # Commit-safe: no key material or private key paths.
    assert "BEGIN" not in text and "PRIVATE" not in text and "priv.pem" not in text


def test_release_checklist_cli_writes_file(tmp_path, official_pack):
    from ceb.cli import main
    pub = _pub(tmp_path)
    rel = build_release_manifest(
        track="A", eval_pack_dir=str(official_pack), public_key_path=pub,
        official_pack_hashes=[compute_eval_pack_hash(official_pack)], root=REPO_ROOT)
    rel_path = tmp_path / "release.json"; rel_path.write_text(json.dumps(rel))
    out = tmp_path / "CHECKLIST.md"
    rc = main(["hosted", "release-checklist", "create", "--track", "A",
               "--release-manifest", str(rel_path), "--out", str(out)])
    assert rc == 0 and out.is_file()
    assert "release checklist" in out.read_text()
