"""Result verification: signature plus integrity checks."""

from ceb.hosted.models import (
    SCHEMA_OFFICIAL_RESULT, SCHEMA_OFFICIAL_RESULT_V1, SCHEMA_TRACK_B_RESULT,
    SCHEMA_VERIFICATION)
from ceb.hosted.official_eval import load_result
from ceb.hosted.signing import (
    ALGORITHM_ED25519, ALGORITHM_HMAC, get_signing_key, verify_any)

_ACCEPTED_SCHEMAS = (SCHEMA_OFFICIAL_RESULT, SCHEMA_OFFICIAL_RESULT_V1,
                     SCHEMA_TRACK_B_RESULT)


def verify_result_file(path, *, public_key=None, hmac_key=None):
    """Verify a result file. Returns a JSON-serializable verdict.

    `authentic` is true only when the signature was checked against a TRUSTED
    key — an out-of-band public key (Ed25519) or the operator HMAC secret. An
    Ed25519 result verified only against its own EMBEDDED public key proves
    internal consistency, not authenticity (an attacker can sign a forged
    result with their own key and embed it), so it is reported with
    `authentic: false` and `signature_trust: "embedded-self-described"`.
    Supply `--public-key` to obtain a real verdict. An unsigned result is never
    authentic.
    """
    result = load_result(path)
    ok, detail = verify_any(result, public_key=public_key, hmac_key=hmac_key)
    algorithm = (result.get("signature") or {}).get("algorithm")

    if algorithm == ALGORITHM_ED25519:
        # Trust requires an out-of-band public key; the embedded copy does not.
        trust = "supplied-public-key" if public_key is not None \
            else "embedded-self-described"
        trusted = public_key is not None
    elif algorithm == ALGORITHM_HMAC:
        # Verifying HMAC requires the operator secret, so a passing HMAC check
        # is by construction against a trusted key.
        trust = "operator-hmac-key"
        trusted = (hmac_key is not None) or (get_signing_key() is not None)
    else:
        trust = "none"
        trusted = False

    claims_verified = bool(result.get("verified"))
    # A public-official verified result MUST be Ed25519-signed; HMAC and
    # unsigned results can never be authentic-verified.
    public_official_signing = (algorithm == ALGORITHM_ED25519
                               if claims_verified else True)

    verdict = {
        "schema": SCHEMA_VERIFICATION,
        "result_path": str(path),
        "result_schema": result.get("schema"),
        "schema_ok": result.get("schema") in _ACCEPTED_SCHEMAS,
        "claims_verified": claims_verified,
        "signature_algorithm": algorithm,
        "signature_ok": ok,
        "signature_detail": detail,
        "signature_trust": trust,
        "public_official_signing": public_official_signing,
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
    verdict["authentic"] = (verdict["schema_ok"] and ok and trusted
                            and public_official_signing
                            and not verdict["metadata_missing_keys"])
    return verdict
