"""File-backed artifacts with an explicit visibility model.

Visibility levels:
  public   safe for the evaluated agent and public APIs: sanitized feedback,
           public report, leaderboard summaries. MUST NOT contain hidden
           FENs, hidden opening/row ids, hidden move sequences, private
           paths, or raw logs.
  private  operator-only: full round/match reports (start FENs, move lists),
           game movetext, gate reports against hidden data, debug detail.
  admin    reserved for credentials-equivalent material; nothing in v0.3
           writes at this level, but the API treats unknown levels as
           non-public.

Every directory of artifacts carries an artifacts_manifest.json listing each
file's visibility; serving layers (ceb.api) consult the manifest and refuse
to serve anything not explicitly public.
"""

import json
from pathlib import Path

VISIBILITY_PUBLIC = "public"
VISIBILITY_PRIVATE = "private"
VISIBILITY_ADMIN = "admin"

MANIFEST_NAME = "artifacts_manifest.json"
_MANIFEST_SCHEMA = "ceb.artifacts.manifest/v1"


def write_artifact(directory, name, payload, visibility):
    """Write one artifact (dict -> JSON, str -> text) and record it in the
    directory manifest. Returns the artifact path."""
    if visibility not in (VISIBILITY_PUBLIC, VISIBILITY_PRIVATE, VISIBILITY_ADMIN):
        raise ValueError("unknown visibility %r" % visibility)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    if isinstance(payload, (dict, list)):
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    else:
        path.write_text(str(payload), encoding="utf-8")
    manifest = read_manifest(directory)
    manifest["artifacts"][name] = {"visibility": visibility}
    _save_manifest(directory, manifest)
    return path


def register_artifact(directory, name, visibility):
    """Record visibility for a file written by other code (e.g. game text)."""
    manifest = read_manifest(directory)
    manifest["artifacts"][name] = {"visibility": visibility}
    _save_manifest(directory, manifest)


def set_artifact_meta(directory, name, meta):
    """Set a manifest entry's full metadata dict (visibility + any flags)."""
    manifest = read_manifest(directory)
    manifest["artifacts"][name] = dict(meta)
    _save_manifest(directory, manifest)


def artifact_meta(directory, name):
    """The full manifest metadata dict for an artifact, or None if unlisted."""
    manifest = read_manifest(directory)
    meta = manifest["artifacts"].get(name)
    return dict(meta) if isinstance(meta, dict) else None


def read_manifest(directory):
    path = Path(directory) / MANIFEST_NAME
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("artifacts"), dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
    return {"schema": _MANIFEST_SCHEMA, "artifacts": {}}


def _save_manifest(directory, manifest):
    path = Path(directory) / MANIFEST_NAME
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def public_artifacts(directory):
    """Names of artifacts explicitly marked public in the manifest.

    Unknown or unlisted files are treated as non-public (deny by default)."""
    manifest = read_manifest(directory)
    return sorted(
        name for name, meta in manifest["artifacts"].items()
        if isinstance(meta, dict) and meta.get("visibility") == VISIBILITY_PUBLIC
    )


def visibility_of(directory, name):
    """Visibility of one artifact, or None if unlisted (treat as private)."""
    manifest = read_manifest(directory)
    meta = manifest["artifacts"].get(name)
    return meta.get("visibility") if isinstance(meta, dict) else None
