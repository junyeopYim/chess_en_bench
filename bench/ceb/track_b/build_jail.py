"""Isolated Track B candidate build (v0.3.2, section C).

A public official Track B evaluation must never execute candidate-owned build
scripts on the host. Instead a TRUSTED operator wrapper builds both baseline
and candidate inside a Docker build jail:

  - candidate/baseline source tree mounted READ-ONLY at /src,
  - a writable output dir at /out,
  - the trusted wrapper mounted READ-ONLY at /wrapper.sh,
  - --network none, read-only root + tmpfs /tmp,
  - CPU / memory / pids limits, no-new-privileges, non-root,
  - NOTHING of the repository or the private eval pack mounted.

The wrapper contract is:

    /wrapper.sh <source_dir_readonly> <output_dir_writable> <engine_relpath>

It must read source from /src (read-only), build into /out (copying to a
writable location first if the build dirties the tree), and leave an executable
engine at /out/<engine_relpath>. The same wrapper builds baseline and
candidate, so build settings are identical and operator-controlled.

The build image defaults to the engine jail image (it already carries
gcc/g++/make + bash + python3 and none of the benchmark); operators may build a
dedicated image from infra/docker/track_b_build_jail.Dockerfile.
"""

import os
import subprocess
import uuid
from pathlib import Path

from ceb.jail import docker_engine

BUILD_JAIL_IMAGE = docker_engine.JAIL_IMAGE  # reuse the toolchain jail image
_CONTAINER_PREFIX = "ceb-tbbuild-"
_DEFAULT_LIMITS = {"cpus": "2", "memory": "4g", "pids": "1024"}

MAX_BUILD_OUTPUT_BYTES = 512 * 1024 * 1024   # 512 MiB
MAX_BUILD_OUTPUT_FILES = 10_000


class BuildJailError(RuntimeError):
    pass


def validate_build_output(output_dir, engine_relpath, *,
                          max_bytes=MAX_BUILD_OUTPUT_BYTES,
                          max_files=MAX_BUILD_OUTPUT_FILES):
    """Validate a build output tree before its engine is used (requirement 5).

    Rejects a missing/non-executable/non-regular/symlinked engine, any symlink
    in the tree, and oversized output (total bytes / file count). Returns the
    resolved engine path."""
    output_dir = Path(output_dir)
    engine = output_dir / engine_relpath
    total_bytes = 0
    file_count = 0
    for path in output_dir.rglob("*"):
        if path.is_symlink():
            raise BuildJailError(
                "build output contains a symlink (%s); rejected"
                % path.relative_to(output_dir).as_posix())
        if path.is_file():
            file_count += 1
            if file_count > max_files:
                raise BuildJailError(
                    "build output has more than %d files" % max_files)
            total_bytes += path.stat().st_size
            if total_bytes > max_bytes:
                raise BuildJailError(
                    "build output exceeds %d bytes" % max_bytes)
    if engine.is_symlink():
        raise BuildJailError("built engine is a symlink; rejected")
    if not engine.is_file():
        raise BuildJailError(
            "build did not produce a regular engine file at %r" % engine_relpath)
    import os as _os
    if not _os.access(engine, _os.X_OK):
        engine.chmod(engine.stat().st_mode | 0o111)
    return engine


def _safe_mount_path(path, what):
    resolved = Path(path).resolve()
    text = str(resolved)
    if ":" in text or "\n" in text:
        raise BuildJailError("%s path is unsafe for a docker mount: %r"
                             % (what, text))
    return resolved


def build_in_jail(source_dir, wrapper_path, engine_relpath, *, output_dir,
                  image=None, limits=None, timeout_s=1800):
    """Build a source tree inside the build jail using a trusted wrapper.

    Returns the host path of the produced engine under output_dir. Raises
    BuildJailError on any failure."""
    if not docker_engine.docker_available():
        raise BuildJailError(
            "docker is required for an isolated Track B build but was not found "
            "on PATH. Install Docker, or run the diagnostic host-build path "
            "(which never produces a verified result).")
    source = _safe_mount_path(source_dir, "source")
    if not source.is_dir():
        raise BuildJailError("source tree is not a directory: %s" % source)
    wrapper = _safe_mount_path(wrapper_path, "build wrapper")
    if not wrapper.is_file():
        raise BuildJailError("trusted build wrapper not found: %s" % wrapper)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    output = _safe_mount_path(output, "output")
    if "/" in engine_relpath or engine_relpath in ("", ".", ".."):
        raise BuildJailError("invalid engine relpath %r" % engine_relpath)

    image = image or BUILD_JAIL_IMAGE
    probe = subprocess.run(["docker", "image", "inspect", image],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=30)
    if probe.returncode != 0:
        raise BuildJailError(
            "build jail image %r not found. Build it first:\n"
            "  bash scripts/build_jail_image.sh   (reuses the toolchain image)\n"
            "  # or: bash scripts/build_track_b_build_image.sh" % image)

    lim = {**_DEFAULT_LIMITS, **(limits or {})}
    name = _CONTAINER_PREFIX + uuid.uuid4().hex[:12]
    argv = [
        "docker", "run", "--rm", "--name", name,
        "--network", "none",
        "--read-only",
        "--tmpfs", "/tmp:rw,exec",
        "--cpus", str(lim["cpus"]),
        "--memory", str(lim["memory"]),
        "--pids-limit", str(lim["pids"]),
        "--security-opt", "no-new-privileges",
        "-e", "PYTHONDONTWRITEBYTECODE=1",
        "-v", "%s:/src:ro" % source,
        "-v", "%s:/wrapper.sh:ro" % wrapper,
        "-v", "%s:/out" % output,
        "-w", "/out",
    ]
    if hasattr(os, "getuid"):
        argv += ["--user", "%d:%d" % (os.getuid(), os.getgid())]
    argv += [image, "bash", "/wrapper.sh", "/src", "/out", engine_relpath]

    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout_s)
    except subprocess.TimeoutExpired:
        _kill(name)
        raise BuildJailError("isolated build exceeded %ds" % timeout_s)
    if proc.returncode != 0:
        raise BuildJailError(
            "isolated build failed (exit %d): %s"
            % (proc.returncode, (proc.stderr or proc.stdout or "")[-500:]))

    # Validate the build output (engine present/executable/regular, no
    # symlinks, size/count limits) before the engine is ever run.
    return validate_build_output(output, engine_relpath)


def _kill(name):
    try:
        subprocess.run(["docker", "kill", name], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        pass
