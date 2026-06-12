"""Staged public-artifact promotion (v0.3.2).

Public official evaluation never writes a public artifact directly. Instead it
writes public-DESTINED artifacts STAGED: the file exists on disk but its
manifest entry is `visibility: private` with a `staged_public: true` marker, so
nothing serves it. The leak scanner runs over the staged set, and only if it
passes are the artifacts atomically promoted to `visibility: public`.

If the leak scan fails, nothing is promoted: no public manifest entry exists
for the job attempt, so the worker (which registers only visibility=public
files) publishes nothing. This closes the window where a public file could be
written before it was leak-scanned.
"""

import json
from pathlib import Path

from ceb.storage.artifacts import (
    MANIFEST_NAME, VISIBILITY_PRIVATE, VISIBILITY_PUBLIC, artifact_meta,
    read_manifest, set_artifact_meta,
)

STAGED_FLAG = "staged_public"


def write_staged_public_artifact(directory, name, payload):
    """Write a public-destined artifact in STAGED state (private until promoted)."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    if isinstance(payload, (dict, list)):
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    else:
        path.write_text(str(payload), encoding="utf-8")
    set_artifact_meta(directory, name,
                      {"visibility": VISIBILITY_PRIVATE, STAGED_FLAG: True})
    return path


def register_staged_public(directory, name):
    """Mark an already-written file as staged-public (private until promoted)."""
    set_artifact_meta(directory, name,
                      {"visibility": VISIBILITY_PRIVATE, STAGED_FLAG: True})


def is_staged_public(directory, name):
    meta = artifact_meta(directory, name)
    return bool(meta and meta.get(STAGED_FLAG)
                and meta.get("visibility") != VISIBILITY_PUBLIC)


def staged_public_artifacts(out_dir):
    """[(directory, name), ...] across the whole tree marked staged_public."""
    found = []
    for manifest_path in sorted(Path(out_dir).rglob(MANIFEST_NAME)):
        directory = manifest_path.parent
        manifest = read_manifest(directory)
        for name, meta in sorted(manifest["artifacts"].items()):
            if (isinstance(meta, dict) and meta.get(STAGED_FLAG)
                    and meta.get("visibility") != VISIBILITY_PUBLIC):
                found.append((directory, name))
    return found


def promote_public_artifacts(out_dir):
    """Promote every staged_public artifact in the tree to public.

    Returns the list of relative names promoted."""
    out_dir = Path(out_dir)
    promoted = []
    for directory, name in staged_public_artifacts(out_dir):
        set_artifact_meta(directory, name, {"visibility": VISIBILITY_PUBLIC})
        try:
            promoted.append((directory / name).relative_to(out_dir).as_posix())
        except ValueError:
            promoted.append(name)
    return promoted
