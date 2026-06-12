"""Result verification: signature plus integrity checks."""

from ceb.hosted.official_eval import load_result
from ceb.hosted.signing import verify_result as verify_signature


def verify_result_file(path, key=None):
    """Verify a result file. Returns a JSON-serializable verdict."""
    result = load_result(path)
    ok, detail = verify_signature(result, key=key)
    verdict = {
        "schema": "ceb.hosted.verification/v1",
        "result_path": str(path),
        "schema_ok": result.get("schema") == "ceb.hosted.official_result/v1",
        "claims_verified": bool(result.get("verified")),
        "signature_ok": ok,
        "signature_detail": detail,
        "metadata_present": isinstance(result.get("metadata"), dict),
    }
    required_metadata = (
        "benchmark_version", "git_commit", "eval_pack_hash",
        "opponent_pool_hash", "opening_suite_hash", "random_seed", "verified",
    )
    metadata = result.get("metadata") or {}
    verdict["metadata_missing_keys"] = [
        key_name for key_name in required_metadata if key_name not in metadata
    ]
    verdict["authentic"] = (verdict["schema_ok"] and ok
                            and not verdict["metadata_missing_keys"])
    return verdict
