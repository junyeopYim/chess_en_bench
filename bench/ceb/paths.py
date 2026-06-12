"""Repository path discovery.

The benchmark reads track configs and public data relative to the repo root.
Resolution order: CEB_ROOT env var, walk up from cwd, walk up from this
module (works for editable installs).
"""

import os
from pathlib import Path

_ROOT_MARKERS = ("tracks", "pyproject.toml")


def _looks_like_root(path):
    return (path / "tracks").is_dir() and (path / "pyproject.toml").is_file()


def find_repo_root(start=None):
    """Best-effort repo root. Raises FileNotFoundError if not found."""
    env = os.environ.get("CEB_ROOT")
    if env:
        p = Path(env).resolve()
        if _looks_like_root(p):
            return p
        raise FileNotFoundError("CEB_ROOT=%s does not look like a chess_en_bench root" % env)

    for base in (Path.cwd(), Path(__file__).resolve()):
        p = base if base.is_dir() else base.parent
        for candidate in [p] + list(p.parents):
            if _looks_like_root(candidate):
                return candidate
    raise FileNotFoundError(
        "could not locate chess_en_bench repo root; run from the repo or set CEB_ROOT")


def tracks_dir(root=None):
    return (root or find_repo_root()) / "tracks"


def track_dir(track, root=None):
    """'A' or 'a_from_scratch' -> tracks/a_from_scratch, similarly for B."""
    name = {"a": "a_from_scratch", "b": "b_stockfish_opt"}.get(
        str(track).lower(), str(track))
    d = tracks_dir(root) / name
    if not d.is_dir():
        raise FileNotFoundError("unknown track %r (no directory %s)" % (track, d))
    return d


def runs_dir(root=None):
    d = (root or find_repo_root()) / "runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def artifacts_dir(root=None):
    d = (root or find_repo_root()) / "artifacts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def web_static_dir(root=None):
    return (root or find_repo_root()) / "web" / "static"
