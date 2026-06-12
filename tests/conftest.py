"""Shared test fixtures, including a TRUSTED official eval pack.

The committed demo pack (examples/eval_packs/tiny_private) can never produce a
verified result (no official manifest, committed/demo path). Verified-path
tests build an official pack OUTSIDE the repo (under pytest's tmp) with a
proper ceb.eval_pack.manifest/v1 manifest.
"""

import json
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TINY_PACK = REPO_ROOT / "examples" / "eval_packs" / "tiny_private"

OFFICIAL_MANIFEST = {
    "schema": "ceb.eval_pack.manifest/v1",
    "pack_id": "ceb-test-2026s1",
    "name": "Test Official Pack",
    "track": "both",
    "season": "2026-s1",
    "official": True,
    "visibility": "private",
    "openings_mode": "replace",
}


def make_official_pack(dest, *, manifest_overrides=None):
    """Build a trusted official eval pack at dest (outside the repo)."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("fen_hidden.jsonl", "perft_hidden.jsonl",
                 "openings_hidden.jsonl"):
        shutil.copy(TINY_PACK / name, dest / name)
    manifest = dict(OFFICIAL_MANIFEST)
    if manifest_overrides:
        manifest.update(manifest_overrides)
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return dest


def official_pack_hash(dest):
    from ceb.hosted.eval_pack_trust import compute_eval_pack_hash
    return compute_eval_pack_hash(dest)


@pytest.fixture
def official_pack(tmp_path):
    return make_official_pack(tmp_path / "official_pack")


@pytest.fixture(scope="module")
def official_pack_module(tmp_path_factory):
    return make_official_pack(tmp_path_factory.mktemp("offpack") / "official_pack")
