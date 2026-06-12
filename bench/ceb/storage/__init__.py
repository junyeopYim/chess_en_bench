"""Artifact storage with an explicit public/private visibility model."""

from ceb.storage.artifacts import (
    VISIBILITY_PUBLIC, VISIBILITY_PRIVATE, VISIBILITY_ADMIN,
    write_artifact, register_artifact, read_manifest, public_artifacts,
    visibility_of, set_artifact_meta, artifact_meta,
)

__all__ = [
    "VISIBILITY_PUBLIC", "VISIBILITY_PRIVATE", "VISIBILITY_ADMIN",
    "write_artifact", "register_artifact", "read_manifest",
    "public_artifacts", "visibility_of", "set_artifact_meta", "artifact_meta",
]
