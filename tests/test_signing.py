"""Tests for result signing and reproducibility metadata (P0.5)."""

import shutil
from pathlib import Path

from ceb.hosted.metadata import build_metadata, hash_directory
from ceb.hosted.signing import sign_result, verify_result

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
    assert metadata["benchmark_version"] == "0.3.0"
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
