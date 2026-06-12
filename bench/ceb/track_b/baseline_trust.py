"""Track B baseline trust (v0.3.3, requirement 3).

A verified Track B result must be scored against a TRUSTED baseline. Three
trust modes are recognised:

  stockfish-lock  the baseline tree is a git checkout whose HEAD matches the
                  pinned commit in tracks/b_stockfish_opt/stockfish.lock.
  hash            the baseline tree's content hash is in an operator allowlist
                  (--track-b-baseline-hash / CEB_TRACK_B_BASELINE_HASHES /
                  --track-b-baseline-registry).
  toy             (--dev-allow-toy-baseline) an untrusted toy baseline used for
                  local tests; the result is forced to verified=false.

The trust report is recorded in result metadata under `track_b`.
"""

import subprocess
from pathlib import Path

from ceb import paths
from ceb.hosted.metadata import hash_directory
from ceb.sanitize import SanitizedError
from ceb.track_b.stockfish import load_lock

ENV_BASELINE_HASHES = "CEB_TRACK_B_BASELINE_HASHES"


class BaselineTrustError(SanitizedError, ValueError):
    pass


def _git_head(tree):
    try:
        proc = subprocess.run(["git", "-C", str(tree), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def _matches_lock(head, lock):
    commit = str(lock.get("commit", "") or "").strip()
    if not head or len(commit) < 7:
        return False
    # The lock pins a (possibly short) commit prefix; the full HEAD sha must
    # start with it. Only this direction is valid — a short HEAD that happens
    # to be a prefix of the lock commit must NOT match.
    return head.startswith(commit)


def validate_track_b_baseline(baseline_src, *, root=None, allowed_hashes=None,
                              allow_toy=False):
    """Validate the Track B baseline. Returns a trust report dict; raises
    BaselineTrustError when no trust mode applies and allow_toy is False."""
    if root is None:
        root = paths.find_repo_root()
    baseline_src = Path(baseline_src)
    if not baseline_src.is_dir():
        raise BaselineTrustError("baseline tree not found",
                                 "baseline not found: %s" % baseline_src)
    tree_hash = hash_directory(baseline_src)
    try:
        lock = load_lock(root)
    except (FileNotFoundError, OSError, ValueError):
        lock = {}

    head = _git_head(baseline_src)
    if _matches_lock(head, lock):
        return {
            "baseline_trusted": True,
            "baseline_trust_mode": "stockfish-lock",
            "baseline_tree_hash": tree_hash,
            "stockfish_lock": {"release": lock.get("release"),
                               "tag": lock.get("tag"),
                               "commit": lock.get("commit")},
            "head_commit": head,
        }

    allow = set(allowed_hashes or [])
    if allow and tree_hash in allow:
        return {
            "baseline_trusted": True,
            "baseline_trust_mode": "hash",
            "baseline_tree_hash": tree_hash,
            "stockfish_lock": None,
        }

    if allow_toy:
        return {
            "baseline_trusted": False,
            "baseline_trust_mode": "toy",
            "baseline_tree_hash": tree_hash,
            "stockfish_lock": None,
        }

    raise BaselineTrustError(
        "Track B baseline is not trusted: it is neither a pinned Stockfish "
        "checkout (HEAD matching stockfish.lock) nor in the baseline hash "
        "allowlist. Supply --track-b-baseline-hash / "
        "CEB_TRACK_B_BASELINE_HASHES, use a pinned Stockfish checkout, or pass "
        "--dev-allow-toy-baseline for a diagnostic (unverified) result")


def resolve_baseline_hashes(*, environ=None, cli_hashes=None, registry_path=None):
    from ceb.hosted.eval_pack_trust import resolve_hash_allowlist
    return resolve_hash_allowlist(env_var=ENV_BASELINE_HASHES, environ=environ,
                                  cli_hashes=cli_hashes,
                                  registry_path=registry_path)
