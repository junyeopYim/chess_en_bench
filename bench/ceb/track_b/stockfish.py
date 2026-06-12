"""Pinned-Stockfish status for Track B.

The baseline is pinned in tracks/b_stockfish_opt/stockfish.lock
(Stockfish 18, tag sf_18, commit cb3d4ee). Official evaluation never uses a
moving branch. Sources are expected at third_party/stockfish (gitignored);
scripts/setup_stockfish.sh fetches and checks out the pinned ref.
"""

import shutil
import subprocess
from pathlib import Path

from ceb import paths
from ceb.config import load_simple_yaml

STOCKFISH_DIR = "third_party/stockfish"


def load_lock(root=None):
    lock_path = paths.track_dir("B", root) / "stockfish.lock"
    return load_simple_yaml(lock_path)


def _git_head(repo_dir):
    git = shutil.which("git")
    if not git:
        return None
    try:
        proc = subprocess.run(
            [git, "-C", str(repo_dir), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def stockfish_status(root=None):
    """JSON-serializable status of the Track B baseline setup."""
    if root is None:
        root = paths.find_repo_root()
    lock = load_lock(root)
    sf_dir = root / STOCKFISH_DIR
    status = {
        "schema": "ceb.track_b.status/v1",
        "lock": lock,
        "stockfish_dir": str(sf_dir),
        "present": sf_dir.is_dir() and (sf_dir / "src").is_dir(),
        "head_commit": None,
        "commit_matches_lock": None,
        "actions": [],
    }
    if not status["present"]:
        status["actions"].append(
            "Stockfish sources not found. Run: bash scripts/setup_stockfish.sh")
        return status
    head = _git_head(sf_dir)
    status["head_commit"] = head
    pinned = str(lock.get("commit", ""))
    if head is None:
        status["commit_matches_lock"] = None
        status["actions"].append(
            "could not read git HEAD in %s; verify the checkout manually" % sf_dir)
    else:
        status["commit_matches_lock"] = head.startswith(pinned)
        if not status["commit_matches_lock"]:
            status["actions"].append(
                "HEAD %s does not match pinned commit %s; "
                "run: git -C %s checkout %s"
                % (head[:12], pinned, sf_dir, lock.get("tag", pinned)))
    if not shutil.which("make") or not shutil.which("g++"):
        status["actions"].append(
            "building Stockfish needs make and a C++ compiler "
            "(e.g. apt install build-essential)")
    if not status["actions"]:
        status["actions"].append(
            "ready: build with `cd %s/src && make -j build` and evaluate "
            "candidate vs baseline" % STOCKFISH_DIR)
    return status
