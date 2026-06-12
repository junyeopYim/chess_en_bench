"""Docker backend for the engine jail.

The jailed engine container gets:
  - ONLY the submission workspace, mounted read-only at /submission
    (no repository, no eval packs, no opponents, no other runs)
  - --network none
  - read-only root filesystem + tmpfs /tmp
  - CPU / memory / pids limits
  - --security-opt no-new-privileges, non-root (host uid:gid)
  - stdio only: UCI flows over `docker run -i` stdin/stdout, bounded by the
    existing UCIClient safeguards

The jail image (infra/docker/engine_jail.Dockerfile) contains a Python
runtime and NOTHING of the benchmark — the `ceb` package is intentionally
absent so an engine cannot import evaluator code even inside the jail.
"""

import os
import subprocess
import uuid

from pathlib import Path

JAIL_IMAGE = "chess-en-bench-jail:0.3"
SUBMISSION_MOUNT = "/submission"
CONTAINER_PREFIX = "ceb-jail-"

DEFAULT_LIMITS = {"cpus": "1", "memory": "1g", "pids": "128"}

# Containers started this process; cleanup_containers() force-kills any
# stragglers (a hostile engine ignoring stdin EOF would otherwise linger).
_LIVE_CONTAINERS = []


class DockerJailError(RuntimeError):
    pass


def docker_available():
    import shutil
    return shutil.which("docker") is not None


def validated_workspace(workspace):
    resolved = Path(workspace).resolve()
    if not resolved.is_dir():
        raise DockerJailError("workspace is not a directory: %s" % resolved)
    text = str(resolved)
    if ":" in text or "\n" in text:
        raise DockerJailError(
            "workspace path contains characters unsafe for a docker mount: %r"
            % text)
    return resolved


def _base_argv(workspace, image, limits, writable, interactive):
    workspace = validated_workspace(workspace)
    limits = {**DEFAULT_LIMITS, **(limits or {})}
    name = CONTAINER_PREFIX + uuid.uuid4().hex[:12]
    _LIVE_CONTAINERS.append(name)
    argv = ["docker", "run", "--rm", "--name", name]
    if interactive:
        argv.append("-i")
    argv += [
        "--network", "none",
        "--read-only",
        "--tmpfs", "/tmp",
        "--cpus", str(limits["cpus"]),
        "--memory", str(limits["memory"]),
        "--pids-limit", str(limits["pids"]),
        "--security-opt", "no-new-privileges",
        "-e", "PYTHONDONTWRITEBYTECODE=1",
        "-v", "%s:%s%s" % (workspace, SUBMISSION_MOUNT,
                           "" if writable else ":ro"),
        "-w", SUBMISSION_MOUNT,
    ]
    if hasattr(os, "getuid"):
        argv += ["--user", "%d:%d" % (os.getuid(), os.getgid())]
    argv.append(image)
    return argv


def build_engine_argv(workspace, image=JAIL_IMAGE, limits=None,
                      engine_name="engine"):
    """argv that runs the submission's engine inside the jail, speaking
    UCI over the container's stdin/stdout. Workspace is read-only."""
    if "/" in engine_name or engine_name in ("", ".", ".."):
        raise DockerJailError("invalid engine name %r" % engine_name)
    argv = _base_argv(workspace, image, limits, writable=False, interactive=True)
    argv.append(SUBMISSION_MOUNT + "/" + engine_name)
    return argv


def build_build_argv(workspace, image=JAIL_IMAGE, limits=None):
    """argv that runs the submission's build.sh inside the jail (workspace
    writable so ./engine can be produced; still no network)."""
    argv = _base_argv(workspace, image, limits, writable=True, interactive=False)
    argv += ["bash", SUBMISSION_MOUNT + "/build.sh"]
    return argv


def ensure_ready(image=JAIL_IMAGE):
    if not docker_available():
        raise DockerJailError(
            "docker is required for --engine-jail docker but was not found "
            "on PATH. Install Docker, or rerun with --engine-jail none "
            "(host execution; only for trusted submissions).")
    probe = subprocess.run(["docker", "image", "inspect", image],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=30)
    if probe.returncode != 0:
        raise DockerJailError(
            "engine jail image %r not found. Build it first:\n"
            "  bash scripts/build_jail_image.sh" % image)


def cleanup_containers():
    """Force-kill any jail containers started by this process (best effort).

    Engines normally exit on stdin EOF and --rm removes the container; this
    reaps hostile engines that ignore EOF."""
    while _LIVE_CONTAINERS:
        name = _LIVE_CONTAINERS.pop()
        try:
            subprocess.run(["docker", "kill", name],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            pass
