"""Submission snapshots: clean copies of agent workspaces.

The worker never evaluates the live workspace — it snapshots it (rejecting
symlinks outright), hashes the tree, and evaluates the snapshot. This pins
what was evaluated and stops post-submission edits or symlink tricks.
"""

import shutil
from pathlib import Path

from ceb.hosted.metadata import hash_directory
from ceb.sanitize import SanitizedError

_SKIP_DIRS = {".git", "__pycache__", ".pytest_cache"}


class SubmissionError(SanitizedError, ValueError):
    pass


def snapshot_workspace(workspace, dest):
    """Copy a workspace into dest (a new directory). Returns (path, tree_hash).

    Rejects symlinks anywhere in the tree and non-regular files.
    """
    workspace = Path(workspace).resolve()
    if not workspace.is_dir():
        raise SubmissionError("workspace is not a directory: %s" % workspace)
    dest = Path(dest)
    if dest.exists():
        raise SubmissionError("snapshot destination already exists: %s" % dest)
    dest.mkdir(parents=True)

    for path in sorted(workspace.rglob("*")):
        rel = path.relative_to(workspace)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        if path.is_symlink():
            shutil.rmtree(dest, ignore_errors=True)
            raise SubmissionError(
                "submission rejected: symlink at %r (symlinks are not "
                "allowed in submissions)" % str(rel))
        target = dest / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        else:
            shutil.rmtree(dest, ignore_errors=True)
            raise SubmissionError(
                "submission rejected: non-regular file at %r" % str(rel))
    return dest, hash_directory(dest)
