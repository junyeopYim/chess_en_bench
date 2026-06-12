"""Diff whitelist checking for Track B.

A candidate tree may differ from the pinned baseline only in files matching
allowed_paths.txt patterns; anything matching forbidden_paths.txt (or not
matching any allowed pattern) is a violation. Patterns are fnmatch globs on
POSIX-style paths relative to the tree root.
"""

import fnmatch
import hashlib
from pathlib import Path

_SKIP_DIRS = {".git", ".hg", ".svn", "__pycache__"}


def load_patterns(path):
    patterns = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns


def _matches(rel_path, patterns):
    return any(fnmatch.fnmatch(rel_path, pat) for pat in patterns)


def _file_digest(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_files(root):
    """Relative POSIX paths of all regular files under root."""
    root = Path(root)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        yield rel.as_posix()


def changed_files(baseline, candidate):
    """Compare trees by content hash. Returns {added, removed, modified}."""
    baseline, candidate = Path(baseline), Path(candidate)
    base_files = set(iter_files(baseline))
    cand_files = set(iter_files(candidate))
    added = sorted(cand_files - base_files)
    removed = sorted(base_files - cand_files)
    modified = []
    for rel in sorted(base_files & cand_files):
        if _file_digest(baseline / rel) != _file_digest(candidate / rel):
            modified.append(rel)
    return {"added": added, "removed": removed, "modified": modified}


def check_diff(baseline, candidate, allowed_patterns, forbidden_patterns=()):
    """Whitelist check. Returns a JSON-serializable report with `passed`."""
    changes = changed_files(baseline, candidate)
    all_changed = [("added", p) for p in changes["added"]] \
        + [("removed", p) for p in changes["removed"]] \
        + [("modified", p) for p in changes["modified"]]

    allowed, violations = [], []
    for kind, rel in all_changed:
        entry = {"path": rel, "change": kind}
        if _matches(rel, forbidden_patterns):
            entry["reason"] = "matches forbidden pattern"
            violations.append(entry)
        elif not _matches(rel, allowed_patterns):
            entry["reason"] = "not covered by the allowed-paths whitelist"
            violations.append(entry)
        else:
            allowed.append(entry)
    return {
        "schema": "ceb.track_b.diff_check/v1",
        "baseline": str(baseline),
        "candidate": str(candidate),
        "changed_total": len(all_changed),
        "allowed_changes": allowed,
        "violations": violations,
        "passed": not violations,
    }
