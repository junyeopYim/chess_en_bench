"""Engine jail front-end: resolve how the untrusted engine is launched.

Modes:
  none    host execution (trusted/local development; v0.2 behavior)
  docker  the engine runs in the docker jail (official hosted evaluation)

Hidden eval packs combine safely with the docker jail: the evaluator reads
the pack on the host and only ever sends individual `position fen ...` UCI
lines into the jail's stdin — the pack directory is never mounted.
"""

from pathlib import Path

from ceb.jail import docker_engine
from ceb.sanitize import SanitizedError

JAIL_MODES = ("none", "docker")


class EngineJailError(SanitizedError, RuntimeError):
    pass


def _check_mode(mode):
    if mode not in JAIL_MODES:
        raise EngineJailError("unknown engine jail mode %r (use one of: %s)"
                              % (mode, ", ".join(JAIL_MODES)))


def engine_command(workspace, mode="none", image=None, limits=None,
                   engine_name="engine"):
    """argv to launch the submission's UCI engine under the given jail mode.

    Returns (argv, cwd): cwd is the workspace for host execution and None
    for the docker jail (the engine's cwd is /submission inside the jail).
    """
    _check_mode(mode)
    workspace = Path(workspace).resolve()
    if mode == "none":
        return [str(workspace / engine_name)], str(workspace)
    try:
        docker_engine.ensure_ready(image or docker_engine.JAIL_IMAGE)
        argv = docker_engine.build_engine_argv(
            workspace, image=image or docker_engine.JAIL_IMAGE, limits=limits,
            engine_name=engine_name)
    except docker_engine.DockerJailError as exc:
        raise EngineJailError(str(exc))
    return argv, None


def build_workspace_command(workspace, mode="none", image=None, limits=None):
    """argv to run the submission's build.sh under the given jail mode, or
    None when the gate should run it on the host (mode 'none')."""
    _check_mode(mode)
    if mode == "none":
        return None
    try:
        docker_engine.ensure_ready(image or docker_engine.JAIL_IMAGE)
        return docker_engine.build_build_argv(
            workspace, image=image or docker_engine.JAIL_IMAGE, limits=limits)
    except docker_engine.DockerJailError as exc:
        raise EngineJailError(str(exc))


def cleanup_jails():
    """Reap any jail containers started by this process."""
    docker_engine.cleanup_containers()
