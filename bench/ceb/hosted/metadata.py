"""Reproducibility metadata for official results.

Collects everything needed to reproduce or audit a result: benchmark
version, git commit, image digests, content hashes of the eval pack /
opponent pool / opening suite, hardware and software fingerprints, and the
random seed. Fields that cannot be determined locally are explicit nulls,
never silently omitted.
"""

import hashlib
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from ceb import __version__


def _run(argv, timeout=10):
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def hash_directory(directory):
    """Deterministic sha256 over a directory's relative paths + contents."""
    directory = Path(directory)
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(directory).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(path.read_bytes())
        digest.update(b"\x01")
    return "sha256:" + digest.hexdigest()


# VCS / cache directories excluded from a SOURCE content hash.
_SOURCE_HASH_SKIP_DIRS = {".git", "__pycache__", ".pytest_cache"}


def source_tree_hash(directory):
    """Deterministic sha256 over a tree's SOURCE content, EXCLUDING VCS/cache
    directories (.git, __pycache__, .pytest_cache). Unlike hash_directory this
    is the scored source content and is stable between a git checkout and a
    snapshot of the same source (which has no .git)."""
    directory = Path(directory)
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        rel = path.relative_to(directory)
        if any(part in _SOURCE_HASH_SKIP_DIRS for part in rel.parts):
            continue
        if not path.is_file():
            continue
        digest.update(rel.as_posix().encode("utf-8"))
        digest.update(b"\x00")
        digest.update(path.read_bytes())
        digest.update(b"\x01")
    return "sha256:" + digest.hexdigest()


def hash_json(payload):
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def hash_file(path):
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git_commit(root):
    return _run(["git", "-C", str(root), "rev-parse", "HEAD"])


def image_digest(image):
    if not shutil.which("docker"):
        return None
    out = _run(["docker", "image", "inspect", "--format", "{{.Id}}", image],
               timeout=20)
    return out or None


def _cpu_model():
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or None


def _compiler():
    gxx = shutil.which("g++") or shutil.which("clang++")
    if not gxx:
        return None
    out = _run([gxx, "--version"])
    return out.splitlines()[0] if out else None


def build_metadata(*, root, eval_pack_dir=None, eval_pack_id=None,
                   opening_suite=None, random_seed=None, verified=False,
                   cpu_cores=1, memory_limit=None,
                   evaluator_image=None, jail_image=None):
    """Assemble the official-result metadata block."""
    from ceb.jail.docker_engine import JAIL_IMAGE
    from ceb.match import opponents as opponents_module

    root = Path(root)
    fastchess = shutil.which("fastchess")
    metadata = {
        "benchmark_version": __version__,
        "git_commit": git_commit(root),
        "evaluator_image_digest": image_digest(
            evaluator_image or "chess-en-bench-evaluator:0.2"),
        "engine_jail_image_digest": image_digest(jail_image or JAIL_IMAGE),
        "eval_pack_id": eval_pack_id,
        "eval_pack_hash": (hash_directory(eval_pack_dir)
                           if eval_pack_dir else None),
        "opponent_pool_hash": hash_file(opponents_module.__file__),
        "opening_suite_hash": (hash_json(opening_suite)
                               if opening_suite is not None else None),
        "hardware": {
            "cpu_model": _cpu_model(),
            "cpu_cores": cpu_cores,
            "memory_limit": memory_limit,
        },
        "software": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "compiler": _compiler(),
            "fastchess": fastchess,
            "stockfish_baseline": "sf_18/cb3d4ee",
        },
        "random_seed": random_seed,
        "verified": bool(verified),
    }
    return metadata
