"""Tests for the Docker sandbox (no Docker daemon required by default)."""

import os
import subprocess
from pathlib import Path

import pytest

from ceb.sandbox import docker_runner
from ceb.sandbox.docker_runner import (
    SandboxError, build_gate_argv, build_round_argv, inside_sandbox,
    run_gate_in_docker, DEFAULT_IMAGE, INSIDE_SANDBOX_ENV,
    REPO_MOUNT, WORKSPACE_MOUNT,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples" / "submissions" / "minimal_uci_engine_python"


def test_gate_argv_is_locked_down():
    argv = build_gate_argv(REPO_ROOT, EXAMPLE, strict=True)
    assert argv[:3] == ["docker", "run", "--rm"]
    joined = " ".join(argv)
    assert "--network none" in joined
    assert "--read-only" in joined
    assert "--pids-limit 256" in joined
    assert "--security-opt no-new-privileges" in joined
    assert "%s=1" % INSIDE_SANDBOX_ENV in joined
    assert "%s:%s:ro" % (REPO_ROOT, REPO_MOUNT) in joined
    assert "%s:%s" % (EXAMPLE, WORKSPACE_MOUNT) in joined
    # The in-container command targets the mounted workspace, not host paths.
    tail = argv[argv.index(DEFAULT_IMAGE) + 1:]
    assert tail[:3] == ["ceb", "gate", "run"]
    assert WORKSPACE_MOUNT in tail
    assert "--strict" in tail
    if hasattr(os, "getuid"):
        assert "--user" in argv  # non-root inside the container


def test_round_argv_pins_inferred_run_id(tmp_path):
    run_dir = tmp_path / "demo"
    workspace = run_dir / "workspace"
    workspace.mkdir(parents=True)
    (run_dir / "state.json").write_text("{}")
    argv = build_round_argv(REPO_ROOT, workspace, round_number=2, quick=True)
    tail = argv[argv.index(DEFAULT_IMAGE) + 1:]
    assert tail[:3] == ["ceb", "round", "run"]
    assert "--quick" in tail
    assert tail[tail.index("--run-id") + 1] == "demo"


def test_workspace_path_validation(tmp_path):
    with pytest.raises(SandboxError, match="not a directory"):
        build_gate_argv(REPO_ROOT, tmp_path / "missing")
    weird = tmp_path / "with:colon"
    weird.mkdir()
    with pytest.raises(SandboxError, match="unsafe"):
        build_gate_argv(REPO_ROOT, weird)


def test_missing_docker_is_actionable(monkeypatch):
    monkeypatch.setattr(docker_runner.shutil, "which", lambda name: None)
    with pytest.raises(SandboxError, match="docker is required"):
        run_gate_in_docker(REPO_ROOT, EXAMPLE)


def test_recursion_guard(monkeypatch):
    monkeypatch.setenv(INSIDE_SANDBOX_ENV, "1")
    assert inside_sandbox()
    with pytest.raises(SandboxError, match="refusing to nest"):
        run_gate_in_docker(REPO_ROOT, EXAMPLE)


def _docker_image_ready():
    import shutil as _shutil
    if os.environ.get("CEB_DOCKER_TESTS") != "1" or not _shutil.which("docker"):
        return False
    probe = subprocess.run(["docker", "image", "inspect", DEFAULT_IMAGE],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return probe.returncode == 0


@pytest.mark.skipif(not _docker_image_ready(),
                    reason="set CEB_DOCKER_TESTS=1 with docker + evaluator "
                           "image built to run the sandbox integration test")
def test_sandboxed_gate_passes_example_engine():
    rc = run_gate_in_docker(REPO_ROOT, EXAMPLE)
    assert rc == 0
