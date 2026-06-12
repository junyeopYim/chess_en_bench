"""Official-readiness check (v0.3.3, requirement 10).

`ceb hosted readiness check` reports whether a deployment can be declared
public-official ready. With --strict-public-official the pinning / key-match /
baseline / wrapper-hash anchors become BLOCKING (FAIL), not warnings.
"""

from pathlib import Path

from ceb import __version__, paths

SCHEMA = "ceb.hosted.readiness/v2"
_MIN_VERSION = (0, 3, 3)


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
                    build_wrapper_hashes=None, build_wrapper_registry=None,
                    track_b_baseline_hashes=None, track_b_baseline_registry=None,
                    baseline_src=None, require_server=False,
                    strict_public_official=False, root=None):
    """Return a readiness report dict with per-check results and `ready`."""
    if root is None:
        try:
            root = paths.find_repo_root()
        except FileNotFoundError:
            root = None
    track = str(track).upper()
    strict = bool(strict_public_official)
    is_b = track in ("B", "BOTH")
    checks = []

    checks.append(_check(
        "package_version", _version_tuple(__version__) >= _MIN_VERSION,
        "ceb %s (need >= %s)" % (__version__, ".".join(map(str, _MIN_VERSION)))))

    if db_path:
        checks.append(_db_schema_check(db_path))
    else:
        checks.append(_check("db_schema_migrated", False, "no --db given",
                             required=False))

    from ceb.jail import docker_engine
    docker_ok = docker_engine.docker_available()
    checks.append(_check("docker_available", docker_ok,
                         "docker on PATH" if docker_ok else "docker not found"))
    checks.append(_check(
        "engine_jail_image", docker_ok and _image_present(docker_engine.JAIL_IMAGE),
        docker_engine.JAIL_IMAGE))
    if is_b:
        from ceb.track_b.build_jail import BUILD_JAIL_IMAGE
        checks.append(_check(
            "build_jail_image",
            docker_ok and _image_present(BUILD_JAIL_IMAGE), BUILD_JAIL_IMAGE))

    # Trusted + pinned official eval pack.
    checks.extend(_eval_pack_checks(eval_pack_dir, track, root,
                                    official_pack_hashes, official_pack_registry,
                                    strict))
    checks.append(_check("demo_pack_rejected", _demo_pack_rejected(track, root),
                         "committed demo pack cannot verify"))

    # Ed25519 signing key + public key + keypair match.
    checks.extend(_key_checks(signing_key_path, public_key_path, strict))

    from ceb.hosted.profiles import get_profile
    checks.append(_check("smoke_not_verifiable",
                         not get_profile("smoke").verifiable,
                         "smoke profile is diagnostic-only"))
    checks.append(_check(
        "official_profiles_verifiable",
        get_profile("official").verifiable
        and get_profile("final-production").verifiable,
        "official + final-production are verifiable"))

    from ceb.rounds.round_runner import DEFAULT_ROUND_MODES, MODE_FINAL_PRODUCTION
    cfg = DEFAULT_ROUND_MODES[MODE_FINAL_PRODUCTION]
    total = len(cfg["opponents"]) * cfg["games_per_opponent"]
    checks.append(_check("final_production_game_floor", total >= 2000,
                         "%d games configured (floor 2000)" % total))

    if is_b:
        checks.extend(_track_b_checks(
            build_wrapper, build_wrapper_hashes, build_wrapper_registry,
            track_b_baseline_hashes, track_b_baseline_registry, baseline_src,
            root, strict))

    if require_server:
        import os
        token = os.environ.get("CEB_ADMIN_TOKEN")
        checks.append(_check("admin_token_configured", bool(token),
                             "CEB_ADMIN_TOKEN set" if token
                             else "set CEB_ADMIN_TOKEN to enable admin endpoints"))

    ready = all(c["ok"] for c in checks if c["required"])
    return {"schema": SCHEMA, "version": __version__, "track": track,
            "strict_public_official": strict, "ready": ready, "checks": checks}


# ----- check groups -----------------------------------------------------------

def _db_schema_check(db_path):
    try:
        from ceb.hosted import db as hosted_db
        conn = hosted_db.connect(db_path)
        try:
            jcols = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
            rcols = {r["name"] for r in conn.execute("PRAGMA table_info(results)")}
        finally:
            conn.close()
        missing = ({"worker_id", "attempt_count", "lease_expires_at",
                    "public_detail"} - jcols) | \
                  ({"profile", "verification_grade", "track"} - rcols)
        return _check("db_schema_migrated", not missing,
                      "missing columns: %s" % sorted(missing) if missing
                      else "jobs/results columns present")
    except Exception as exc:  # noqa: BLE001
        return _check("db_schema_migrated", False, "db error: %s" % type(exc).__name__)


def _eval_pack_checks(eval_pack_dir, track, root, cli_hashes, registry, strict):
    out = []
    if not eval_pack_dir:
        out.append(_check("official_eval_pack_trusted", False, "no --eval-pack given"))
        out.append(_check("official_pack_pinned", False, "no --eval-pack given",
                          required=strict))
        return out
    from ceb.hosted.eval_pack_trust import (
        resolve_allowed_hashes, validate_official_eval_pack, EvalPackTrustError)
    allowed = resolve_allowed_hashes(cli_hashes=cli_hashes, registry_path=registry)
    try:
        trust = validate_official_eval_pack(
            eval_pack_dir, track=("A" if track == "BOTH" else track),
            root=root, allowed_hashes=allowed)
        out.append(_check("official_eval_pack_trusted", True,
                          "pack_id=%s hash=%s" % (trust["pack_id"],
                                                  trust["pack_hash"][:23])))
        out.append(_check(
            "official_pack_pinned", trust["allowlist_checked"],
            "pinned to an allowlisted hash" if trust["allowlist_checked"]
            else "no hash allowlist — pin via --official-pack-hash / "
                 "CEB_OFFICIAL_EVAL_PACK_HASHES (required for public official)",
            required=strict))
    except EvalPackTrustError as exc:
        out.append(_check("official_eval_pack_trusted", False, exc.public_message))
        out.append(_check("official_pack_pinned", False,
                          "eval pack not trusted", required=strict))
    return out


def _key_checks(signing_key_path, public_key_path, strict):
    from ceb.hosted.signing import (
        ed25519_private_key_path, load_private_key, load_public_key,
        public_key_fingerprint, SigningError)
    out = []
    key_path = ed25519_private_key_path(explicit_path=signing_key_path)
    private = None
    if key_path:
        try:
            private = load_private_key(key_path)
        except (SigningError, OSError, ValueError):
            private = None
    out.append(_check("ed25519_signing_key", private is not None,
                      "private key configured and loadable" if private
                      else "set CEB_SIGNING_PRIVATE_KEY or --signing-key"))

    public = None
    if public_key_path:
        try:
            public = load_public_key(public_key_path)
        except (SigningError, OSError, ValueError):
            public = None
    out.append(_check("public_key_verify_ready", public is not None,
                      "public key loadable: %s" % (public_key_fingerprint(public)
                                                   if public else "-")
                      if public else "supply --public-key (out-of-band) for "
                                     "third-party verification",
                      required=strict))

    if private is not None and public is not None:
        match = public_key_fingerprint(private.public_key()) == \
            public_key_fingerprint(public)
        out.append(_check("keypair_match", match,
                          "private/public key fingerprints match (%s)"
                          % public_key_fingerprint(public) if match
                          else "private and public keys DO NOT match",
                          required=strict))
    else:
        out.append(_check("keypair_match", False,
                          "need both a loadable private and public key to "
                          "check the keypair", required=strict))
    return out


def _track_b_checks(build_wrapper, wrapper_hashes, wrapper_registry,
                    baseline_hashes, baseline_registry, baseline_src, root, strict):
    out = []
    wrapper_ok, wdetail, wrapper_path = _build_wrapper_present(build_wrapper)
    out.append(_check("track_b_build_wrapper", wrapper_ok, wdetail))

    # Build wrapper hash pinned.
    if wrapper_path:
        from ceb.hosted.build_wrappers import (
            compute_wrapper_hash, resolve_wrapper_hashes)
        allowed = resolve_wrapper_hashes(cli_hashes=wrapper_hashes,
                                         registry_path=wrapper_registry)
        wh = compute_wrapper_hash(wrapper_path)
        out.append(_check("build_wrapper_pinned", bool(allowed) and wh in allowed,
                          "wrapper hash %s %s" % (wh[:23],
                          "pinned" if (allowed and wh in allowed) else
                          "NOT in allowlist (pin via --build-wrapper-hash)"),
                          required=strict))
    else:
        out.append(_check("build_wrapper_pinned", False,
                          "no build wrapper to pin", required=strict))

    # Baseline trust available.
    out.append(_baseline_trust_check(baseline_hashes, baseline_registry,
                                     baseline_src, root, strict))

    # Bench/speed sanity available.
    out.append(_check("bench_speed_sanity", True,
                      "bench/speed sanity runs for verified Track B; real "
                      "public Track B requires pinned Stockfish supporting bench",
                      required=strict))

    # Track B hosted API endpoint importable.
    out.append(_track_b_api_check(strict))
    return out


def _baseline_trust_check(baseline_hashes, baseline_registry, baseline_src,
                          root, strict):
    from ceb.track_b.baseline_trust import (
        resolve_baseline_hashes, validate_track_b_baseline, BaselineTrustError)
    allowed = resolve_baseline_hashes(cli_hashes=baseline_hashes,
                                      registry_path=baseline_registry)
    # If a concrete baseline tree is given, VALIDATE it (lock or hash) rather
    # than trusting a non-empty allowlist alone.
    if baseline_src:
        try:
            rep = validate_track_b_baseline(baseline_src, root=root,
                                            allowed_hashes=allowed, allow_toy=False)
            return _check("track_b_baseline_trust", rep["baseline_trusted"],
                          "baseline trusted via %s" % rep["baseline_trust_mode"],
                          required=strict)
        except BaselineTrustError as exc:
            return _check("track_b_baseline_trust", False, exc.public_message,
                          required=strict)
    if allowed:
        return _check("track_b_baseline_trust", True,
                      "%d baseline hash(es) allowlisted (each submission's "
                      "baseline is validated against it at eval time)" % len(allowed),
                      required=strict)
    # Try a pinned Stockfish checkout.
    sf = (Path(root) if root else None)
    candidate = (sf / "third_party" / "stockfish") if sf else None
    if candidate and candidate.is_dir():
        try:
            rep = validate_track_b_baseline(candidate, root=root, allow_toy=False)
            return _check("track_b_baseline_trust", rep["baseline_trusted"],
                          "baseline trust mode: %s" % rep["baseline_trust_mode"],
                          required=strict)
        except BaselineTrustError as exc:
            return _check("track_b_baseline_trust", False, exc.public_message,
                          required=strict)
    return _check("track_b_baseline_trust", False,
                  "no baseline hash allowlist and no pinned Stockfish checkout; "
                  "supply --track-b-baseline-hash or a stockfish.lock checkout",
                  required=strict)


def _track_b_api_check(strict):
    try:
        from ceb.api.main import app
        routes = {getattr(r, "path", "") for r in app.routes}
        ok = any("track-b-submissions" in p for p in routes)
        return _check("track_b_api_endpoint", ok,
                      "POST /api/hosted/runs/{run_id}/track-b-submissions"
                      if ok else "Track B submission endpoint missing",
                      required=strict)
    except Exception as exc:  # noqa: BLE001 - server extra may be absent
        return _check("track_b_api_endpoint", False,
                      "API import failed (%s); install .[server]" % type(exc).__name__,
                      required=strict)


# ----- small helpers ----------------------------------------------------------

def _image_present(image):
    import subprocess
    try:
        return subprocess.run(["docker", "image", "inspect", image],
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
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
        return False
    except EvalPackTrustError:
        return True


def _build_wrapper_present(build_wrapper):
    import os
    if not build_wrapper:
        return False, "no --build-wrapper given (required for verified Track B)", None
    try:
        from ceb.hosted.build_wrappers import validate_build_wrapper, BuildWrapperError
        path = validate_build_wrapper(build_wrapper)
    except BuildWrapperError as exc:
        return False, exc.public_message, None
    if not os.access(path, os.X_OK):
        return False, "build wrapper is not executable (chmod +x)", None
    return True, "trusted wrapper present and executable", path
