"""Official-readiness check (v0.3.2, section H).

`ceb hosted readiness check` tells an operator whether a deployment can be
declared public-official-ready. It runs a battery of positive checks and
returns a structured report plus a nonzero exit when not ready.
"""

from pathlib import Path

from ceb import __version__, paths

SCHEMA = "ceb.hosted.readiness/v1"
_MIN_VERSION = (0, 3, 2)


def _version_tuple(text):
    parts = []
    for token in str(text).split("."):
        num = "".join(c for c in token if c.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts[:3] + [0] * (3 - len(parts)))


def _check(name, ok, detail, required=True):
    return {"name": name, "ok": bool(ok), "required": required, "detail": detail}


def readiness_check(*, db_path=None, eval_pack_dir=None, public_key_path=None,
                    track="A", build_wrapper=None, signing_key_path=None,
                    official_pack_hashes=None, official_pack_registry=None,
                    require_server=False, root=None):
    """Return a readiness report dict with per-check results and `ready`."""
    if root is None:
        try:
            root = paths.find_repo_root()
        except FileNotFoundError:
            root = None
    track = str(track).upper()
    checks = []

    checks.append(_check(
        "package_version", _version_tuple(__version__) >= _MIN_VERSION,
        "ceb %s (need >= %s)" % (__version__, ".".join(map(str, _MIN_VERSION)))))

    # DB schema migrated.
    if db_path:
        try:
            from ceb.hosted import db as hosted_db
            conn = hosted_db.connect(db_path)
            try:
                jcols = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
                rcols = {r["name"] for r in conn.execute("PRAGMA table_info(results)")}
            finally:
                conn.close()
            need_j = {"worker_id", "attempt_count", "lease_expires_at",
                      "public_detail"}
            need_r = {"profile", "verification_grade", "track"}
            missing = (need_j - jcols) | (need_r - rcols)
            checks.append(_check("db_schema_migrated", not missing,
                                 "missing columns: %s" % sorted(missing)
                                 if missing else "jobs/results columns present"))
        except Exception as exc:  # noqa: BLE001
            checks.append(_check("db_schema_migrated", False,
                                 "db error: %s" % type(exc).__name__))
    else:
        checks.append(_check("db_schema_migrated", False,
                             "no --db given", required=False))

    # Docker + jail images.
    from ceb.jail import docker_engine
    docker_ok = docker_engine.docker_available()
    checks.append(_check("docker_available", docker_ok,
                         "docker on PATH" if docker_ok else "docker not found"))
    checks.append(_check(
        "engine_jail_image", docker_ok and _image_present(docker_engine.JAIL_IMAGE),
        docker_engine.JAIL_IMAGE))
    if track in ("B", "BOTH"):
        from ceb.track_b.build_jail import BUILD_JAIL_IMAGE
        checks.append(_check(
            "build_jail_image",
            docker_ok and _image_present(BUILD_JAIL_IMAGE), BUILD_JAIL_IMAGE))

    # Trusted official eval pack.
    if eval_pack_dir:
        from ceb.hosted.eval_pack_trust import (
            resolve_allowed_hashes, validate_official_eval_pack,
            EvalPackTrustError)
        allowed = resolve_allowed_hashes(cli_hashes=official_pack_hashes,
                                         registry_path=official_pack_registry)
        try:
            trust = validate_official_eval_pack(
                eval_pack_dir, track=("A" if track == "BOTH" else track),
                root=root, allowed_hashes=allowed)
            checks.append(_check("official_eval_pack_trusted", True,
                                 "pack_id=%s hash=%s" % (trust["pack_id"],
                                                         trust["pack_hash"][:23])))
            # Recommend pinning the pack hash; a self-declared official manifest
            # with no allowlist is trusted but unpinned (warning, not blocking).
            checks.append(_check(
                "official_pack_pinned", trust["allowlist_checked"],
                "pinned to an allowlisted hash" if trust["allowlist_checked"]
                else "no hash allowlist configured — pin via --official-pack-hash "
                     "/ CEB_OFFICIAL_EVAL_PACK_HASHES for a public season",
                required=False))
        except EvalPackTrustError as exc:
            checks.append(_check("official_eval_pack_trusted", False,
                                 exc.public_message))
    else:
        checks.append(_check("official_eval_pack_trusted", False,
                             "no --eval-pack given"))

    # Demo pack must be rejected for verified profiles.
    checks.append(_check("demo_pack_rejected", _demo_pack_rejected(track, root),
                         "committed demo pack cannot verify"))

    # Ed25519 signing key + public key.
    from ceb.hosted.signing import ed25519_private_key_path
    key_path = ed25519_private_key_path(explicit_path=signing_key_path)
    key_ok = bool(key_path) and _key_loads(key_path, private=True)
    checks.append(_check("ed25519_signing_key", key_ok,
                         "private key configured and loadable" if key_ok
                         else "set CEB_SIGNING_PRIVATE_KEY or --signing-key"))
    if public_key_path:
        pub_ok = _key_loads(public_key_path, private=False)
        checks.append(_check("public_key_verify_ready", pub_ok,
                             "public key loadable" if pub_ok
                             else "could not load --public-key"))
    else:
        checks.append(_check("public_key_verify_ready", False,
                             "no --public-key given (needed for third-party "
                             "verification)", required=False))

    # Profile policy.
    from ceb.hosted.profiles import get_profile
    checks.append(_check("smoke_not_verifiable",
                         not get_profile("smoke").verifiable,
                         "smoke profile is diagnostic-only"))
    checks.append(_check(
        "official_profiles_verifiable",
        get_profile("official").verifiable
        and get_profile("final-production").verifiable,
        "official + final-production are verifiable"))

    # final-production game floor.
    from ceb.rounds.round_runner import DEFAULT_ROUND_MODES, MODE_FINAL_PRODUCTION
    cfg = DEFAULT_ROUND_MODES[MODE_FINAL_PRODUCTION]
    total = len(cfg["opponents"]) * cfg["games_per_opponent"]
    checks.append(_check("final_production_game_floor", total >= 2000,
                         "%d games configured (floor 2000)" % total))

    # Track B build wrapper.
    if track in ("B", "BOTH"):
        wrapper_ok, wdetail = _build_wrapper_ok(build_wrapper)
        checks.append(_check("track_b_build_wrapper", wrapper_ok, wdetail))

    # Admin token for server mode.
    if require_server:
        import os
        checks.append(_check("admin_token_configured",
                             bool(os.environ.get("CEB_ADMIN_TOKEN")),
                             "CEB_ADMIN_TOKEN set" if os.environ.get("CEB_ADMIN_TOKEN")
                             else "set CEB_ADMIN_TOKEN to enable admin endpoints"))

    ready = all(c["ok"] for c in checks if c["required"])
    return {"schema": SCHEMA, "version": __version__, "track": track,
            "ready": ready, "checks": checks}


def _image_present(image):
    import subprocess
    try:
        return subprocess.run(["docker", "image", "inspect", image],
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _key_loads(path, *, private):
    from ceb.hosted.signing import load_private_key, load_public_key, SigningError
    try:
        (load_private_key if private else load_public_key)(path)
        return True
    except (SigningError, OSError, ValueError):
        return False


def _demo_pack_rejected(track, root):
    from ceb.hosted.eval_pack_trust import (
        validate_official_eval_pack, EvalPackTrustError)
    demo = (Path(root) if root else paths.find_repo_root()) \
        / "examples" / "eval_packs" / "tiny_private"
    if not demo.is_dir():
        return True
    try:
        validate_official_eval_pack(
            demo, track=("A" if track == "BOTH" else track), root=root)
        return False  # should NOT have validated
    except EvalPackTrustError:
        return True


def _build_wrapper_ok(build_wrapper):
    import os
    if not build_wrapper:
        return False, "no --build-wrapper given (required for verified Track B)"
    try:
        from ceb.hosted.build_wrappers import validate_build_wrapper, BuildWrapperError
        path = validate_build_wrapper(build_wrapper)
    except BuildWrapperError as exc:
        return False, exc.public_message
    if not os.access(path, os.X_OK):
        return False, "build wrapper is not executable (chmod +x)"
    return True, "trusted wrapper present and executable"
