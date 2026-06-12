"""Tests for result signing (HMAC + Ed25519) and reproducibility metadata."""

import shutil
from pathlib import Path

import pytest

from ceb import __version__
from ceb.hosted.metadata import build_metadata, hash_directory
from ceb.hosted.signing import (
    generate_keypair, load_private_key, load_public_key, sign_result,
    sign_result_ed25519, verify_result, verify_result_ed25519, verify_any,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
TINY_PACK = REPO_ROOT / "examples" / "eval_packs" / "tiny_private"

KEY = b"test-signing-key"


def _result():
    return {"schema": "ceb.hosted.official_result/v1", "run_id": "r",
            "score": {"final_score": 700.0}, "verified": True}


def test_sign_and_verify_roundtrip():
    result = sign_result(_result(), key=KEY)
    assert result["signature"]["status"] == "signed"
    assert result["signature"]["algorithm"] == "hmac-sha256"
    ok, detail = verify_result(result, key=KEY)
    assert ok, detail


def test_tampered_result_fails_verification():
    result = sign_result(_result(), key=KEY)
    result["score"]["final_score"] = 9999.0
    ok, detail = verify_result(result, key=KEY)
    assert not ok
    assert "MISMATCH" in detail


def test_wrong_key_fails_verification():
    result = sign_result(_result(), key=KEY)
    ok, _ = verify_result(result, key=b"other-key")
    assert not ok


def test_unsigned_mode_is_explicit_and_never_authentic(monkeypatch):
    monkeypatch.delenv("CEB_SIGNING_KEY", raising=False)
    result = sign_result(_result())
    assert result["signature"]["status"] == "unsigned"
    assert "NO cryptographic authenticity" in result["signature"]["note"]
    ok, detail = verify_result(result, key=KEY)
    assert not ok
    assert "unsigned" in detail


def test_env_key_used(monkeypatch):
    monkeypatch.setenv("CEB_SIGNING_KEY", "env-key")
    result = sign_result(_result())
    assert result["signature"]["status"] == "signed"
    ok, _ = verify_result(result)
    assert ok


def test_metadata_required_keys():
    metadata = build_metadata(root=REPO_ROOT, eval_pack_dir=TINY_PACK,
                              eval_pack_id="tiny", opening_suite=[{"id": "x"}],
                              random_seed=1234, verified=True)
    for key in ("benchmark_version", "git_commit", "evaluator_image_digest",
                "engine_jail_image_digest", "eval_pack_id", "eval_pack_hash",
                "opponent_pool_hash", "opening_suite_hash", "hardware",
                "software", "random_seed", "verified"):
        assert key in metadata, key
    assert metadata["benchmark_version"] == __version__
    assert metadata["eval_pack_hash"].startswith("sha256:")
    assert metadata["software"]["stockfish_baseline"] == "sf_18/cb3d4ee"
    assert metadata["random_seed"] == 1234
    assert metadata["hardware"]["cpu_cores"] == 1


def test_eval_pack_hash_changes_with_contents(tmp_path):
    pack_a = tmp_path / "a"
    shutil.copytree(TINY_PACK, pack_a)
    hash_before = hash_directory(pack_a)
    assert hash_before == hash_directory(TINY_PACK)  # deterministic copy
    (pack_a / "fen_hidden.jsonl").write_text(
        '{"id": "changed", "fen": "8/8/8/3k4/8/8/4Q3/4K3 w - - 0 1"}\n')
    assert hash_directory(pack_a) != hash_before


# ----- Ed25519 public-key signing (P0.9) --------------------------------------

def test_ed25519_keygen_sign_verify_roundtrip(tmp_path):
    key_id = generate_keypair(tmp_path / "priv.pem", tmp_path / "pub.pem")
    assert key_id.startswith("ed25519:")
    private = load_private_key(tmp_path / "priv.pem")
    public = load_public_key(tmp_path / "pub.pem")
    result = sign_result_ed25519(_result(), private)
    sig = result["signature"]
    assert sig["status"] == "signed"
    assert sig["algorithm"] == "ed25519"
    assert sig["key_id"] == key_id == sig["public_key_fingerprint"]
    ok, detail = verify_result_ed25519(result, public)
    assert ok, detail


def test_ed25519_tampered_result_fails(tmp_path):
    generate_keypair(tmp_path / "priv.pem", tmp_path / "pub.pem")
    private = load_private_key(tmp_path / "priv.pem")
    public = load_public_key(tmp_path / "pub.pem")
    result = sign_result_ed25519(_result(), private)
    result["score"]["final_score"] = 9999.0
    ok, detail = verify_result_ed25519(result, public)
    assert not ok
    assert "MISMATCH" in detail


def test_ed25519_wrong_key_fails(tmp_path):
    generate_keypair(tmp_path / "p1.pem", tmp_path / "pub1.pem")
    generate_keypair(tmp_path / "p2.pem", tmp_path / "pub2.pem")
    result = sign_result_ed25519(_result(), load_private_key(tmp_path / "p1.pem"))
    ok, detail = verify_result_ed25519(result, load_public_key(tmp_path / "pub2.pem"))
    assert not ok
    assert "key_id mismatch" in detail


def test_unsigned_result_never_authentic_ed25519(tmp_path):
    generate_keypair(tmp_path / "priv.pem", tmp_path / "pub.pem")
    public = load_public_key(tmp_path / "pub.pem")
    ok, detail = verify_result_ed25519(_result(), public)  # no signature block
    assert not ok
    assert "unsigned" in detail


def test_verify_any_routes_by_algorithm_and_does_not_confuse(tmp_path):
    generate_keypair(tmp_path / "priv.pem", tmp_path / "pub.pem")
    public = load_public_key(tmp_path / "pub.pem")
    ed = sign_result_ed25519(_result(), load_private_key(tmp_path / "priv.pem"))
    mac = sign_result(_result(), key=KEY)
    # Each verifies under its own algorithm ...
    assert verify_any(ed, public_key=public)[0] is True
    assert verify_any(mac, hmac_key=KEY)[0] is True
    # ... and an HMAC result is NOT accepted by the public-key verifier.
    ok, detail = verify_result_ed25519(mac, public)
    assert not ok
    assert "not Ed25519" in detail


def _full_ed25519_result_file(tmp_path, private_key):
    import json
    metadata = {"benchmark_version": "x", "git_commit": None,
                "eval_pack_hash": "sha256:0", "opponent_pool_hash": "sha256:0",
                "opening_suite_hash": "sha256:0", "random_seed": 1000,
                "verified": True}
    result = {"schema": "ceb.hosted.official_result/v2", "run_id": "r",
              "verified": True, "score": {"final_score": 700.0},
              "metadata": metadata}
    sign_result_ed25519(result, private_key)
    path = tmp_path / "result.json"
    path.write_text(json.dumps(result))
    return path


def test_verifier_embedded_key_is_not_authentic(tmp_path):
    # A result verified only against its OWN embedded public key proves
    # internal consistency, NOT authenticity (an attacker can sign with their
    # own key and embed it). authentic must require an out-of-band public key.
    from ceb.hosted.verifier import verify_result_file

    generate_keypair(tmp_path / "priv.pem", tmp_path / "pub.pem")
    private = load_private_key(tmp_path / "priv.pem")
    public = load_public_key(tmp_path / "pub.pem")
    path = _full_ed25519_result_file(tmp_path, private)

    # No public key supplied: signature is internally consistent but NOT trusted.
    verdict = verify_result_file(path)
    assert verdict["signature_ok"] is True
    assert verdict["signature_trust"] == "embedded-self-described"
    assert verdict["authentic"] is False

    # Supplied out-of-band public key: now authentic.
    trusted = verify_result_file(path, public_key=public)
    assert trusted["signature_trust"] == "supplied-public-key"
    assert trusted["authentic"] is True


def test_verifier_attacker_key_not_authentic_against_operator_key(tmp_path):
    # Attacker signs a forged result with their own key (and embeds it). A
    # verifier holding the OPERATOR's public key must reject it.
    from ceb.hosted.verifier import verify_result_file

    generate_keypair(tmp_path / "op_priv.pem", tmp_path / "op_pub.pem")
    generate_keypair(tmp_path / "att_priv.pem", tmp_path / "att_pub.pem")
    operator_pub = load_public_key(tmp_path / "op_pub.pem")
    attacker_priv = load_private_key(tmp_path / "att_priv.pem")
    path = _full_ed25519_result_file(tmp_path, attacker_priv)

    verdict = verify_result_file(path, public_key=operator_pub)
    assert verdict["authentic"] is False  # key_id mismatch
    # Without any out-of-band key it is still NOT authentic (self-described).
    assert verify_result_file(path)["authentic"] is False
