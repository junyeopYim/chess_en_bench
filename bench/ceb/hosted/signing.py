"""Result signing: public-key (Ed25519) and legacy operator HMAC (P0.9).

Two algorithms, chosen explicitly so they can never be confused:

  ed25519 (recommended, public verification)
    Asymmetric signature over a canonical JSON serialization. Anyone holding
    the operator's PUBLIC key can verify authenticity; the private key never
    leaves the operator. This is what a public hosted benchmark should use.
    The signature block embeds the public key and its fingerprint (key_id) so
    a result file is self-describing, but third-party trust comes from
    verifying against a public key obtained out-of-band, not from the embedded
    copy.

  hmac-sha256 (legacy, operator-internal)
    Symmetric MAC keyed by CEB_SIGNING_KEY. Authenticates results only to
    holders of that secret key (i.e. the operator); it is NOT public-key
    attestation. Kept for backward compatibility; new deployments should use
    Ed25519.

Without any key configured, results are written with signature.status =
"unsigned" and never claim cryptographic authenticity. Unsigned results are
never authentic. sign_official_result() picks Ed25519 > HMAC > unsigned.
"""

import base64
import hashlib
import hmac
import json
import os

SIGNING_KEY_ENV = "CEB_SIGNING_KEY"                  # HMAC secret (legacy)
PRIVATE_KEY_ENV = "CEB_SIGNING_PRIVATE_KEY"          # Ed25519 private key path
PUBLIC_KEY_ENV = "CEB_PUBLIC_KEY"                    # Ed25519 public key path

ALGORITHM_HMAC = "hmac-sha256"
ALGORITHM_ED25519 = "ed25519"
ALGORITHM = ALGORITHM_HMAC  # backward-compat alias


class SigningError(RuntimeError):
    pass


def canonical_payload(result):
    """Canonical bytes of a result dict, excluding any signature block."""
    body = {k: v for k, v in result.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


# ----- HMAC (legacy, operator-internal) ---------------------------------------

def get_signing_key(environ=None):
    key = (environ or os.environ).get(SIGNING_KEY_ENV)
    return key.encode("utf-8") if key else None


def sign_result(result, key=None):
    """Attach an HMAC signature block (in place) and return the result dict.

    Legacy/operator-internal. New code should prefer sign_official_result(),
    which selects Ed25519 when a private key is configured.
    """
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
        "algorithm": ALGORITHM_HMAC,
        "note": "symmetric HMAC; verifiable only by holders of the signing key",
        "value": digest,
    }
    return result


def verify_result(result, key=None):
    """Verify an HMAC signature block. Returns (ok: bool, detail: str)."""
    signature = result.get("signature") or {}
    if signature.get("status") != "signed":
        return False, "unsigned result (no cryptographic authenticity)"
    if signature.get("algorithm") != ALGORITHM_HMAC:
        return False, ("signature algorithm is %r, not HMAC; use the public-key "
                       "verifier" % signature.get("algorithm"))
    key = key if key is not None else get_signing_key()
    if not key:
        return False, "no %s configured; cannot verify" % SIGNING_KEY_ENV
    expected = hmac.new(key, canonical_payload(result), hashlib.sha256).hexdigest()
    if hmac.compare_digest(expected, str(signature.get("value", ""))):
        return True, "signature valid (%s)" % ALGORITHM_HMAC
    return False, "signature MISMATCH: result was modified or signed with a different key"


# ----- Ed25519 (recommended, public verification) -----------------------------

def _ed25519():
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519
        from cryptography.hazmat.primitives import serialization
    except ImportError as exc:  # pragma: no cover - exercised only without extra
        raise SigningError(
            "Ed25519 signing needs the 'cryptography' package. Install it with:"
            "\n  pip install -e \".[hosted]\"") from exc
    return ed25519, serialization


def generate_keypair(private_path, public_path):
    """Generate an Ed25519 keypair, writing PEM files. Returns the key_id."""
    ed25519, serialization = _ed25519()
    private_key = ed25519.Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption())
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo)
    from pathlib import Path
    Path(private_path).write_bytes(private_pem)
    try:
        os.chmod(private_path, 0o600)
    except OSError:  # pragma: no cover - platform dependent
        pass
    Path(public_path).write_bytes(public_pem)
    return public_key_fingerprint(public_key)


def load_private_key(path):
    ed25519, serialization = _ed25519()
    from pathlib import Path
    return serialization.load_pem_private_key(Path(path).read_bytes(),
                                              password=None)


def load_public_key(path):
    ed25519, serialization = _ed25519()
    from pathlib import Path
    return serialization.load_pem_public_key(Path(path).read_bytes())


def _public_raw(public_key):
    _, serialization = _ed25519()
    return public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw)


def public_key_fingerprint(public_key):
    """A short, stable key id: sha256 of the raw public key, hex (16 bytes)."""
    return "ed25519:" + hashlib.sha256(_public_raw(public_key)).hexdigest()[:32]


def sign_result_ed25519(result, private_key):
    """Attach an Ed25519 signature block (in place) and return the result."""
    signature = private_key.sign(canonical_payload(result))
    public_key = private_key.public_key()
    result["signature"] = {
        "status": "signed",
        "algorithm": ALGORITHM_ED25519,
        "note": "Ed25519; verifiable by anyone holding the operator public key",
        "key_id": public_key_fingerprint(public_key),
        "public_key_fingerprint": public_key_fingerprint(public_key),
        "public_key": base64.b64encode(_public_raw(public_key)).decode("ascii"),
        "value": base64.b64encode(signature).decode("ascii"),
    }
    return result


def verify_result_ed25519(result, public_key=None):
    """Verify an Ed25519 signature. Returns (ok: bool, detail: str).

    If public_key is None, falls back to the public key embedded in the
    signature block (self-consistency only). For real third-party trust,
    supply a public key obtained out-of-band; this function then also confirms
    the embedded key_id matches it.
    """
    ed25519, _ = _ed25519()
    signature = result.get("signature") or {}
    if signature.get("status") != "signed":
        return False, "unsigned result (no cryptographic authenticity)"
    if signature.get("algorithm") != ALGORITHM_ED25519:
        return False, ("signature algorithm is %r, not Ed25519"
                       % signature.get("algorithm"))
    try:
        sig_bytes = base64.b64decode(str(signature.get("value", "")))
    except (ValueError, TypeError):
        return False, "signature value is not valid base64"

    trusted = "embedded (self-described) public key"
    if public_key is None:
        embedded = signature.get("public_key")
        if not embedded:
            return False, "no public key supplied and none embedded"
        try:
            public_key = ed25519.Ed25519PublicKey.from_public_bytes(
                base64.b64decode(embedded))
        except (ValueError, TypeError):
            return False, "embedded public key is malformed"
    else:
        trusted = "supplied public key"
        # When a trusted key is supplied, confirm key_id agreement so a result
        # cannot claim a different signer than the one that actually signed it.
        claimed = signature.get("key_id") or signature.get("public_key_fingerprint")
        actual = public_key_fingerprint(public_key)
        if claimed and claimed != actual:
            return False, ("key_id mismatch: result claims %s but supplied key "
                           "is %s" % (claimed, actual))

    try:
        public_key.verify(sig_bytes, canonical_payload(result))
    except Exception:  # noqa: BLE001 - InvalidSignature and friends
        return False, ("signature MISMATCH: result was modified or signed with "
                       "a different key")
    return True, "signature valid (%s, %s)" % (ALGORITHM_ED25519, trusted)


# ----- dispatcher -------------------------------------------------------------

def sign_official_result(result, environ=None):
    """Sign a result with the strongest configured algorithm: Ed25519 if a
    private key is configured, else legacy HMAC, else unsigned."""
    environ = environ or os.environ
    private_path = environ.get(PRIVATE_KEY_ENV)
    if private_path:
        return sign_result_ed25519(result, load_private_key(private_path))
    return sign_result(result, key=get_signing_key(environ))


def verify_any(result, *, public_key=None, hmac_key=None):
    """Verify a result by whatever algorithm its signature block declares.

    Returns (ok, detail). Unsigned -> (False, ...). public_key (Ed25519) and
    hmac_key (legacy) are optional overrides; without them, Ed25519 falls back
    to the embedded public key and HMAC falls back to CEB_SIGNING_KEY.
    """
    signature = result.get("signature") or {}
    algorithm = signature.get("algorithm")
    if signature.get("status") != "signed":
        return False, "unsigned result (no cryptographic authenticity)"
    if algorithm == ALGORITHM_ED25519:
        return verify_result_ed25519(result, public_key=public_key)
    if algorithm == ALGORITHM_HMAC:
        return verify_result(result, key=hmac_key)
    return False, "unknown signature algorithm %r" % algorithm
