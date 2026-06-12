"""Docker sandbox for evaluating untrusted submissions.

The sandbox re-invokes `ceb gate run` / `ceb round run` inside a locked-down
container built from infra/docker/evaluator.Dockerfile:

  - --network none                 no network for agent code
  - --read-only + tmpfs /tmp       immutable root filesystem
  - --cpus / --memory / --pids-limit   resource caps
  - --security-opt no-new-privileges
  - non-root: container runs as the invoking host uid:gid
  - repo mounted read-only at /bench; only the workspace and runs/ are writable
  - argv lists everywhere — untrusted paths are never shell-interpolated
  - CEB_INSIDE_SANDBOX=1 prevents recursive sandbox invocation

Build the image once with:  bash scripts/build_evaluator_image.sh
"""

import os
import shutil
import subprocess
from pathlib import Path

DEFAULT_IMAGE = "chess-en-bench-evaluator:0.2"
INSIDE_SANDBOX_ENV = "CEB_INSIDE_SANDBOX"

WORKSPACE_MOUNT = "/sandbox/workspace"
REPO_MOUNT = "/bench"

DEFAULT_LIMITS = {"cpus": "2", "memory": "2g", "pids": "256"}


class SandboxError(RuntimeError):
    """Sandbox cannot run; message is user-facing and actionable."""


def docker_available():
    return shutil.which("docker") is not None


def inside_sandbox(environ=None):
    return bool((environ or os.environ).get(INSIDE_SANDBOX_ENV))


def _validated_dir(path, what):
    """Resolve a host directory for mounting; reject unusable paths."""
    resolved = Path(path).resolve()
    if not resolved.is_dir():
        raise SandboxError("%s is not a directory: %s" % (what, resolved))
    text = str(resolved)
    # ':' is the docker -v field separator; a path containing it could
    # smuggle extra mount options.
    if ":" in text or "\n" in text:
        raise SandboxError("%s path contains characters unsafe for a docker "
                           "mount: %r" % (what, text))
    return resolved


def _docker_base_argv(repo_root, workspace, image, limits):
    repo_root = _validated_dir(repo_root, "repo root")
    workspace = _validated_dir(workspace, "workspace")
    runs_dir = repo_root / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    limits = {**DEFAULT_LIMITS, **(limits or {})}

    argv = [
        "docker", "run", "--rm",
        "--network", "none",
        "--read-only",
        "--tmpfs", "/tmp",
        "--cpus", str(limits["cpus"]),
        "--memory", str(limits["memory"]),
        "--pids-limit", str(limits["pids"]),
        "--security-opt", "no-new-privileges",
        "-e", "%s=1" % INSIDE_SANDBOX_ENV,
        "-e", "CEB_ROOT=%s" % REPO_MOUNT,
        "-v", "%s:%s:ro" % (repo_root, REPO_MOUNT),
        "-v", "%s:%s%s" % (runs_dir, REPO_MOUNT, "/runs"),
        "-v", "%s:%s" % (workspace, WORKSPACE_MOUNT),
        "-w", REPO_MOUNT,
    ]
    if hasattr(os, "getuid"):
        argv += ["--user", "%d:%d" % (os.getuid(), os.getgid())]
    argv.append(image)
    return argv


def build_gate_argv(repo_root, workspace, *, image=DEFAULT_IMAGE, track="A",
                    strict=False, no_match=False, limits=None):
    """Full docker argv for a sandboxed gate run."""
    argv = _docker_base_argv(repo_root, workspace, image, limits)
    argv += ["ceb", "gate", "run", "--track", str(track),
             "--workspace", WORKSPACE_MOUNT]
    if strict:
        argv.append("--strict")
    if no_match:
        argv.append("--no-match")
    return argv


def build_round_argv(repo_root, workspace, *, round_number, image=DEFAULT_IMAGE,
                     track="A", quick=False, run_id=None, limits=None):
    """Full docker argv for a sandboxed round run."""
    argv = _docker_base_argv(repo_root, workspace, image, limits)
    argv += ["ceb", "round", "run", "--track", str(track),
             "--workspace", WORKSPACE_MOUNT, "--round", str(int(round_number))]
    if quick:
        argv.append("--quick")
    # Prepared workspaces are mounted at a fixed path, so the in-container
    # runner cannot infer the run id from runs/<run_id>/workspace; pin the
    # host-side inference result instead.
    if run_id is None:
        from ceb.rounds.round_runner import default_run_id
        run_id = default_run_id(workspace)
    argv += ["--run-id", run_id]
    return argv


def _ensure_ready(image):
    if inside_sandbox():
        raise SandboxError(
            "already inside the evaluation sandbox (%s set); refusing to "
            "nest containers" % INSIDE_SANDBOX_ENV)
    if not docker_available():
        raise SandboxError(
            "docker is required for --sandbox docker but was not found on "
            "PATH. Install Docker, or rerun with --sandbox none (host "
            "execution; only for trusted submissions).")
    probe = subprocess.run(["docker", "image", "inspect", image],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=30)
    if probe.returncode != 0:
        raise SandboxError(
            "evaluator image %r not found. Build it first:\n"
            "  bash scripts/build_evaluator_image.sh" % image)


def _run(argv):
    # Inherit stdout/stderr so gate/round output streams to the operator.
    return subprocess.run(argv).returncode


def run_gate_in_docker(repo_root, workspace, *, image=DEFAULT_IMAGE, track="A",
                       strict=False, no_match=False, limits=None):
    """Run the gate inside the sandbox; returns the container's exit code."""
    _ensure_ready(image)
    return _run(build_gate_argv(repo_root, workspace, image=image, track=track,
                                strict=strict, no_match=no_match, limits=limits))


def run_round_in_docker(repo_root, workspace, *, round_number,
                        image=DEFAULT_IMAGE, track="A", quick=False,
                        run_id=None, limits=None):
    """Run a round inside the sandbox; returns the container's exit code."""
    _ensure_ready(image)
    return _run(build_round_argv(repo_root, workspace, round_number=round_number,
                                 image=image, track=track, quick=quick,
                                 run_id=run_id, limits=limits))
