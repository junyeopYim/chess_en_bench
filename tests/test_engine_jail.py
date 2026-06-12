"""Tests for the engine jail (P0.1). Docker-dependent tests are opt-in."""

import os
import subprocess
from pathlib import Path

import pytest

from ceb.jail import docker_engine
from ceb.jail.docker_engine import (
    JAIL_IMAGE, SUBMISSION_MOUNT, build_build_argv, build_engine_argv,
    cleanup_containers, DockerJailError,
)
from ceb.jail.engine_jail import EngineJailError, engine_command

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples" / "submissions" / "minimal_uci_engine_python"
TINY_PACK = REPO_ROOT / "examples" / "eval_packs" / "tiny_private"


def test_jail_argv_mounts_only_the_workspace():
    argv = build_engine_argv(EXAMPLE)
    joined = " ".join(argv)
    # exactly one mount: the workspace, read-only at /submission
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]
    assert mounts == ["%s:%s:ro" % (EXAMPLE, SUBMISSION_MOUNT)]
    assert "/bench" not in joined          # no repository mount
    assert str(REPO_ROOT) + ":" not in joined
    assert str(TINY_PACK) not in joined    # no eval pack mount, ever
    assert "--network none" in joined
    assert "--read-only" in joined
    assert "--tmpfs /tmp" in joined
    assert "--pids-limit 128" in joined
    assert "--cpus 1" in joined
    assert "--memory 1g" in joined
    assert "--security-opt no-new-privileges" in joined
    if hasattr(os, "getuid"):
        assert "--user" in argv            # non-root
    assert argv[-1] == SUBMISSION_MOUNT + "/engine"
    assert "-i" in argv                    # UCI over stdin/stdout


def test_jail_build_argv_is_writable_but_offline():
    argv = build_build_argv(EXAMPLE)
    joined = " ".join(argv)
    assert "%s:%s" % (EXAMPLE, SUBMISSION_MOUNT) in joined
    assert ":ro" not in joined             # build needs to write ./engine
    assert "--network none" in joined
    assert argv[-2:] == ["bash", SUBMISSION_MOUNT + "/build.sh"]


def test_eval_pack_combines_with_jail_without_mounting_it(monkeypatch):
    # Even with the private pack configured in the environment, the jail
    # argv must never reference it: the evaluator reads it host-side only.
    monkeypatch.setenv("CEB_PRIVATE_EVAL_DIR", str(TINY_PACK))
    argv = build_engine_argv(EXAMPLE)
    assert str(TINY_PACK) not in " ".join(argv)


def test_engine_command_modes(tmp_path):
    argv, cwd = engine_command(EXAMPLE, "none")
    assert argv == [str(EXAMPLE / "engine")]
    assert cwd == str(EXAMPLE)
    with pytest.raises(EngineJailError, match="unknown engine jail mode"):
        engine_command(EXAMPLE, "chroot")


def test_missing_docker_is_actionable(monkeypatch):
    import shutil as shutil_module
    monkeypatch.setattr(shutil_module, "which", lambda name: None)
    with pytest.raises(EngineJailError, match="docker is required"):
        engine_command(EXAMPLE, "docker")


def test_workspace_validation(tmp_path):
    with pytest.raises(DockerJailError, match="not a directory"):
        build_engine_argv(tmp_path / "missing")
    weird = tmp_path / "with:colon"
    weird.mkdir()
    with pytest.raises(DockerJailError, match="unsafe"):
        build_engine_argv(weird)
    with pytest.raises(DockerJailError, match="invalid engine name"):
        build_engine_argv(EXAMPLE, engine_name="../escape")


def test_cleanup_kills_recorded_containers(monkeypatch):
    calls = []
    monkeypatch.setattr(
        docker_engine.subprocess, "run",
        lambda argv, **kw: calls.append(argv) or
        subprocess.CompletedProcess(argv, 0))
    docker_engine._LIVE_CONTAINERS[:] = ["ceb-jail-test1", "ceb-jail-test2"]
    cleanup_containers()
    assert [c[:2] for c in calls] == [["docker", "kill"], ["docker", "kill"]]
    assert not docker_engine._LIVE_CONTAINERS


def _jail_image_ready():
    import shutil as shutil_module
    if os.environ.get("CEB_DOCKER_TESTS") != "1" or not shutil_module.which("docker"):
        return False
    probe = subprocess.run(["docker", "image", "inspect", JAIL_IMAGE],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return probe.returncode == 0


@pytest.mark.skipif(not _jail_image_ready(),
                    reason="set CEB_DOCKER_TESTS=1 with docker + jail image "
                           "built to run jail integration tests")
def test_jailed_engine_plays_over_uci():
    from ceb.chess import START_FEN, parse_fen, generate_legal
    from ceb.uci.client import UCIClient

    argv, cwd = engine_command(EXAMPLE, "docker")
    try:
        with UCIClient(argv, cwd=cwd, name="jailed") as client:
            client.handshake(timeout=30.0)
            client.set_position()
            best = client.go_movetime(100, grace_ms=10000)
        legal = {m.uci() for m in generate_legal(parse_fen(START_FEN))}
        assert best in legal
    finally:
        cleanup_containers()


@pytest.mark.skipif(not _jail_image_ready(),
                    reason="set CEB_DOCKER_TESTS=1 with docker + jail image "
                           "built to run jail integration tests")
def test_gate_passes_with_jailed_engine():
    from ceb.gate.gate_runner import run_gate

    report = run_gate(EXAMPLE, root=REPO_ROOT, quick_match=False,
                      engine_jail="docker")
    assert report.passed, report.human_summary()
