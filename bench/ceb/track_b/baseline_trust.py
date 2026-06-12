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
from ceb.hosted.metadata import source_tree_hash
from ceb.sanitize import SanitizedError
from ceb.track_b.stockfish import load_lock

ENV_BASELINE_HASHES = "CEB_TRACK_B_BASELINE_HASHES"


class BaselineTrustError(SanitizedError, ValueError):
    pass


def _git(tree, *args, timeout=15):
    try:
        proc = subprocess.run(["git", "-C", str(tree), *args],
                              capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _git_head(tree):
    out = _git(tree, "rev-parse", "HEAD")
    return out.strip() if out is not None else None


def git_worktree_clean(tree):
    """True iff the git working tree is fully clean: no tracked modifications,
    no untracked files, and no IGNORED files (a built/polluted tree is not the
    pinned source). --ignore-submodules=none forces submodule changes to be
    reported even when .gitmodules sets `ignore = all`, and --ignored catches
    extra files that .gitignore would otherwise hide."""
    out = _git(tree, "status", "--porcelain", "--untracked-files=all",
               "--ignored", "--ignore-submodules=none")
    return out is not None and out.strip() == ""


def git_submodules_clean(tree):
    """True iff no submodule is out of sync (commit drift) AND no submodule has
    a dirty working tree — vacuously true when there are no submodules."""
    status = _git(tree, "submodule", "status", "--recursive")
    if status is None:
        return False
    for line in status.splitlines():
        if line and line[0] != " ":   # '+', '-', 'U' mark commit drift
            return False
    # Also reject a submodule whose working tree is merely dirty at the right
    # commit (modified tracked files / untracked files inside the submodule).
    dirty = _git(tree, "submodule", "foreach", "--recursive", "--quiet",
                 "git status --porcelain --untracked-files=all --ignored")
    return dirty is not None and dirty.strip() == ""


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
    # Content hash EXCLUDES .git so it is the scored source, stable between a
    # git checkout and a snapshot of the same source.
    tree_hash = source_tree_hash(baseline_src)
    try:
        lock = load_lock(root)
    except (FileNotFoundError, OSError, ValueError):
        lock = {}

    head = _git_head(baseline_src)
    if _matches_lock(head, lock):
        # HEAD matching the lock is NOT enough: the working tree (and any
        # submodules) must be clean, else the scored binary would not be the
        # pinned source. A dirty checkout falls through to hash mode.
        if git_worktree_clean(baseline_src) and git_submodules_clean(baseline_src):
            return {
                "baseline_trusted": True,
                "baseline_trust_mode": "stockfish-lock",
                "baseline_tree_hash": tree_hash,   # content hash recorded
                "worktree_clean": True,
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
