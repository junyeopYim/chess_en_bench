"""Trusted official eval-pack policy (v0.3.2).

A public official `verified: true` result must be produced against an operator
OFFICIAL eval pack, never against a committed demo pack such as
examples/eval_packs/tiny_private. This module is the positive trust path: it
loads and validates an official pack manifest, computes deterministic hashes,
and enforces an optional operator allowlist.

An official pack directory must contain a manifest.json with:

    schema:        "ceb.eval_pack.manifest/v1"
    pack_id:       stable identifier, e.g. "ceb-A-2026s1"
    name:          human label
    track:         "A" | "B" | "both"
    season:        e.g. "2026-s1"
    official:      true
    visibility:    "private"
    openings_mode: "extend" | "replace"

The pack must live OUTSIDE the repository's committed/demo paths (examples/,
tests/) unless an explicit development flag is given. When an operator supplies
an allowlist (env CEB_OFFICIAL_EVAL_PACK_HASHES, CLI --official-pack-hash, or a
registry file), the pack's content hash must be in it. Demo packs may still be
used for the `smoke` profile and tests, but they never satisfy this check and
so can never produce a verified result.
"""

import hashlib
import json
import os
from pathlib import Path

from ceb import paths
from ceb.hosted.metadata import hash_directory
from ceb.sanitize import SanitizedError

MANIFEST_SCHEMA = "ceb.eval_pack.manifest/v1"
TRUST_SCHEMA = "ceb.eval_pack.trust/v1"
ENV_OFFICIAL_HASHES = "CEB_OFFICIAL_EVAL_PACK_HASHES"

_REQUIRED_KEYS = ("schema", "pack_id", "name", "track", "season", "official",
                  "visibility", "openings_mode")
# Repo-relative top-level dirs that mark a committed/demo pack.
_DEMO_DIRS = ("examples", "tests")


class EvalPackTrustError(SanitizedError, ValueError):
    """An eval pack is not a trusted official pack."""


def compute_eval_pack_hash(private_dir):
    """Deterministic sha256 over the pack directory's contents."""
    return hash_directory(private_dir)


def compute_manifest_hash(manifest):
    """Deterministic sha256 over the canonical manifest JSON."""
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_eval_pack_manifest(private_dir):
    """Load and shallow-validate manifest.json. Raises EvalPackTrustError."""
    path = Path(private_dir) / "manifest.json"
    if not path.is_file():
        raise EvalPackTrustError(
            "eval pack has no manifest.json; an official pack needs a "
            "%s manifest" % MANIFEST_SCHEMA)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EvalPackTrustError("eval pack manifest.json is not valid JSON",
                                 "manifest.json parse error: %s" % exc)
    if not isinstance(data, dict):
        raise EvalPackTrustError("eval pack manifest.json must be a JSON object")
    return data


def _is_committed_demo_path(private_dir, root):
    """True if the pack lives under the repo's examples/ or tests/."""
    resolved = Path(private_dir).resolve()
    try:
        rel = resolved.relative_to(Path(root).resolve())
    except ValueError:
        return False
    return bool(rel.parts) and rel.parts[0] in _DEMO_DIRS


def _read_registry_hashes(registry_path):
    out = set()
    if not registry_path:
        return out
    text = Path(registry_path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict) and isinstance(data.get("hashes"), list):
        out |= {str(h).strip() for h in data["hashes"] if str(h).strip()}
    elif isinstance(data, list):
        out |= {str(h).strip() for h in data if str(h).strip()}
    else:
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                out.add(line)
    return out


def resolve_hash_allowlist(*, env_var=None, environ=None, cli_hashes=None,
                           registry_path=None):
    """Merge a hash allowlist from an env var (comma-separated), CLI values
    (repeat/comma), and a registry file (JSON {"hashes":[...]} / list / lines).
    Reused for eval-pack, Track B baseline, and build-wrapper allowlists."""
    out = set()
    if env_var:
        raw = (environ if environ is not None else os.environ).get(env_var)
        if raw:
            out |= {h.strip() for h in raw.split(",") if h.strip()}
    for entry in (cli_hashes or []):
        out |= {h.strip() for h in str(entry).split(",") if h.strip()}
    out |= _read_registry_hashes(registry_path)
    return out


def resolve_allowed_hashes(*, environ=None, cli_hashes=None, registry_path=None):
    """Merge official eval-pack hash allowlists from env, CLI, and a registry."""
    return resolve_hash_allowlist(
        env_var=ENV_OFFICIAL_HASHES, environ=environ, cli_hashes=cli_hashes,
        registry_path=registry_path)


def validate_official_eval_pack(private_dir, *, track, root=None,
                                allowed_hashes=None, allow_demo=False):
    """Validate that private_dir is a trusted official pack for `track`.

    Returns a trust report dict on success; raises EvalPackTrustError otherwise.
    """
    if root is None:
        root = paths.find_repo_root()
    private_dir = Path(private_dir)
    if not private_dir.is_dir():
        raise EvalPackTrustError("eval pack directory not found",
                                 "eval pack not found: %s" % private_dir)

    manifest = load_eval_pack_manifest(private_dir)
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise EvalPackTrustError(
            "eval pack manifest schema is not %s (this looks like a demo or "
            "legacy pack and cannot produce a verified result)" % MANIFEST_SCHEMA)
    missing = [k for k in _REQUIRED_KEYS if k not in manifest]
    if missing:
        raise EvalPackTrustError(
            "official eval pack manifest is missing required keys: %s"
            % ", ".join(missing))
    if manifest.get("official") is not True:
        raise EvalPackTrustError(
            "eval pack manifest does not declare official: true; only official "
            "packs may produce verified results")
    if manifest.get("visibility") != "private":
        raise EvalPackTrustError(
            "official eval pack manifest must declare visibility: private")

    manifest_track = str(manifest.get("track", "")).upper()
    if manifest_track not in ("A", "B", "BOTH"):
        raise EvalPackTrustError(
            "eval pack manifest track must be A, B, or both")
    want = str(track).upper()
    if manifest_track != "BOTH" and manifest_track != want:
        raise EvalPackTrustError(
            "eval pack is declared for track %s but this is a track %s "
            "evaluation" % (manifest_track, want))

    on_demo_path = _is_committed_demo_path(private_dir, root)
    if on_demo_path and not allow_demo:
        raise EvalPackTrustError(
            "eval pack lives under a committed/demo path (examples/ or tests/); "
            "a public official eval pack must be operator-private and outside "
            "the repository")

    pack_hash = compute_eval_pack_hash(private_dir)
    manifest_hash = compute_manifest_hash(manifest)

    allow = set(allowed_hashes or [])
    if allow and pack_hash not in allow:
        raise EvalPackTrustError(
            "eval pack content hash is not in the official allowlist; refusing "
            "to verify against an unrecognised pack",
            "pack hash %s not in allowlist %s" % (pack_hash, sorted(allow)))

    return {
        "schema": TRUST_SCHEMA,
        "trusted": True,
        "pack_id": manifest["pack_id"],
        "name": manifest["name"],
        "track": manifest_track,
        "season": manifest.get("season"),
        "pack_hash": pack_hash,
        "manifest_hash": manifest_hash,
        "allowlist_checked": bool(allow),
        # True only when the demo-path bypass was actually USED (the pack is on
        # a committed/demo path AND allow_demo bypassed the check). A genuine
        # off-repo pack is not poisoned just because --dev-allow-demo-pack was
        # passed.
        "demo_path_allowed": bool(allow_demo and on_demo_path),
    }
