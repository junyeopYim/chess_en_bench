"""Engine jail: isolate the untrusted engine process, not the evaluator.

Unlike the legacy --sandbox docker mode (which re-runs the whole harness in
a container with the repository mounted), the engine jail keeps the
evaluator trusted on the host — it reads hidden eval packs, runs the oracle
and scoring — and confines ONLY the submission engine. The jailed engine
sees nothing but its own workspace, mounted read-only at /submission.
"""

from ceb.jail.engine_jail import (
    JAIL_MODES, EngineJailError, engine_command, build_workspace_command,
    cleanup_jails,
)
from ceb.jail.docker_engine import JAIL_IMAGE, SUBMISSION_MOUNT

__all__ = [
    "JAIL_MODES", "EngineJailError", "engine_command",
    "build_workspace_command", "cleanup_jails", "JAIL_IMAGE",
    "SUBMISSION_MOUNT",
]
