"""Public release manifest (v0.3.3, requirement 9).

`ceb hosted release-manifest create` emits a public, secret-free manifest that
pins every public-official trust anchor for a benchmark season: benchmark
version + git commit, the official eval-pack content hash, the operator public
key FINGERPRINT (never the key), the engine/build jail image digests, and (for
Track B) the pinned baseline and build-wrapper hashes. A public leaderboard
publishes this manifest so anyone can check which anchors a season used.
"""

from pathlib import Path

from ceb import __version__, paths
from ceb.hosted.metadata import git_commit, image_digest
from ceb.sanitize import SanitizedError

SCHEMA = "ceb.release_manifest/v1"

DEFAULT_LIMITATIONS = [
    "single-node hosted backend (SQLite + local filesystem); not a distributed "
    "production service",
    "fastchess is outside the official verified path until PGN oracle "
    "post-validation exists",
    "real hidden eval packs, signing keys, and Stockfish source are operator "
    "artifacts and are never committed",
]

DEFAULT_LEADERBOARD_POLICY = (
    "verified results only; one entry per run = best verified result "
    "(final-tier preferred over official-tier); smoke/diagnostic never appear")


class ReleaseManifestError(SanitizedError, ValueError):
    pass


def _single_hash(resolved, label):
    """Exactly one hash must be pinned for a release season. 0 -> None (caller
    raises required); >1 -> ambiguous error (operator must pin one)."""
    resolved = set(resolved or [])
    if len(resolved) == 1:
        return next(iter(resolved))
    if not resolved:
        return None
    raise ReleaseManifestError(
        "multiple %s hashes configured; pin exactly one for the release "
        "manifest" % label)


def build_release_manifest(*, track, eval_pack_dir, public_key_path,
                           benchmark_version=None, season=None,
                           official_pack_hashes=None, official_pack_registry=None,
                           track_b_baseline_hashes=None,
                           track_b_baseline_registry=None,
                           build_wrapper_hashes=None, build_wrapper_registry=None,
                           leaderboard_policy=None, known_limitations=None,
                           root=None):
    """Build the public release manifest dict. Raises ReleaseManifestError when
    a required public-official anchor is missing or untrusted."""
    if root is None:
        root = paths.find_repo_root()
    track = str(track).upper()
    if track not in ("A", "B"):
        raise ReleaseManifestError("track must be A or B")

    # Eval pack must be trusted AND pinned.
    from ceb.hosted.eval_pack_trust import (
        resolve_allowed_hashes, validate_official_eval_pack, EvalPackTrustError)
    if not eval_pack_dir:
        raise ReleaseManifestError("an official --eval-pack is required")
    allowed = resolve_allowed_hashes(cli_hashes=official_pack_hashes,
                                     registry_path=official_pack_registry)
    if not allowed:
        raise ReleaseManifestError(
            "release manifest requires a pinned official pack hash "
            "(--official-pack-hash / CEB_OFFICIAL_EVAL_PACK_HASHES)")
    try:
        trust = validate_official_eval_pack(eval_pack_dir, track=track, root=root,
                                            allowed_hashes=allowed)
    except EvalPackTrustError as exc:
        raise ReleaseManifestError("official eval pack rejected: %s"
                                   % exc.public_message)

    # Operator public key fingerprint (NEVER the key).
    from ceb.hosted.signing import (
        load_public_key, public_key_fingerprint, SigningError)
    if not public_key_path:
        raise ReleaseManifestError("--public-key is required")
    try:
        fingerprint = public_key_fingerprint(load_public_key(public_key_path))
    except (SigningError, OSError, ValueError) as exc:
        raise ReleaseManifestError("could not load --public-key",
                                   "public key load error: %s" % exc)

    from ceb.jail.docker_engine import JAIL_IMAGE
    manifest = {
        "schema": SCHEMA,
        "benchmark_version": benchmark_version or __version__,
        "git_commit": git_commit(root),
        "track": track,
        "season": season or trust.get("season"),
        "official_eval_pack_id": trust["pack_id"],
        "official_eval_pack_hash": trust["pack_hash"],
        "official_eval_pack_manifest_hash": trust["manifest_hash"],
        "operator_public_key_fingerprint": fingerprint,
        "engine_jail_image": JAIL_IMAGE,
        "engine_jail_image_digest": image_digest(JAIL_IMAGE),
        "track_b_baseline_hash": None,
        "track_b_build_wrapper_hash": None,
        "build_jail_image_digest": None,
        "leaderboard_policy": leaderboard_policy or DEFAULT_LEADERBOARD_POLICY,
        "known_limitations": list(known_limitations or DEFAULT_LIMITATIONS),
    }

    if track == "B":
        from ceb.track_b.baseline_trust import resolve_baseline_hashes
        from ceb.hosted.build_wrappers import resolve_wrapper_hashes
        from ceb.track_b.build_jail import BUILD_JAIL_IMAGE
        baseline = _single_hash(resolve_baseline_hashes(
            cli_hashes=track_b_baseline_hashes,
            registry_path=track_b_baseline_registry), "Track B baseline")
        wrapper = _single_hash(resolve_wrapper_hashes(
            cli_hashes=build_wrapper_hashes,
            registry_path=build_wrapper_registry), "build wrapper")
        if not baseline:
            raise ReleaseManifestError(
                "Track B release manifest requires --track-b-baseline-hash")
        if not wrapper:
            raise ReleaseManifestError(
                "Track B release manifest requires --build-wrapper-hash")
        manifest["track_b_baseline_hash"] = baseline
        manifest["track_b_build_wrapper_hash"] = wrapper
        manifest["build_jail_image_digest"] = image_digest(BUILD_JAIL_IMAGE)

    return manifest
