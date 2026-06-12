"""Result signing (v0.3 MVP).

Symmetric HMAC-SHA256 over a canonical JSON serialization, keyed by the
CEB_SIGNING_KEY environment variable. This authenticates results to anyone
who holds the same key (i.e. the benchmark operator); it is NOT public-key
attestation — third parties cannot verify without the key. Asymmetric
signing is future work and documented as such.

Without a key, results are written with signature.status = "unsigned" and
never claim cryptographic authenticity.
"""

import hashlib
import hmac
import json
import os

SIGNING_KEY_ENV = "CEB_SIGNING_KEY"
ALGORITHM = "hmac-sha256"


def canonical_payload(result):
    """Canonical bytes of a result dict, excluding any signature block."""
    body = {k: v for k, v in result.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def get_signing_key(environ=None):
    key = (environ or os.environ).get(SIGNING_KEY_ENV)
    return key.encode("utf-8") if key else None


def sign_result(result, key=None):
    """Attach a signature block (in place) and return the result dict."""
    key = key if key is not None else get_signing_key()
    if not key:
        result["signature"] = {
            "status": "unsigned",
            "algorithm": None,
            "note": "no %s configured; this result has NO cryptographic "
                    "authenticity" % SIGNING_KEY_ENV,
        }
        return result
    digest = hmac.new(key, canonical_payload(result), hashlib.sha256).hexdigest()
    result["signature"] = {
        "status": "signed",
        "algorithm": ALGORITHM,
        "note": "symmetric HMAC; verifiable only by holders of the signing key",
        "value": digest,
    }
    return result


def verify_result(result, key=None):
    """Verify a result's signature block.

    Returns (ok: bool, detail: str). Unsigned results verify as
    (False, 'unsigned') so callers can never mistake them for authentic.
    """
    signature = result.get("signature") or {}
    if signature.get("status") != "signed":
        return False, "unsigned result (no cryptographic authenticity)"
    key = key if key is not None else get_signing_key()
    if not key:
        return False, "no %s configured; cannot verify" % SIGNING_KEY_ENV
    expected = hmac.new(key, canonical_payload(result), hashlib.sha256).hexdigest()
    if hmac.compare_digest(expected, str(signature.get("value", ""))):
        return True, "signature valid (%s)" % ALGORITHM
    return False, "signature MISMATCH: result was modified or signed with a different key"
