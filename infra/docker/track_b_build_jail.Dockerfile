# Track B build jail image (v0.3.2).
# Build from the repo root:  bash scripts/build_track_b_build_image.sh
#
# An isolated build environment for compiling untrusted Track B candidate/
# baseline source via a TRUSTED operator wrapper. It carries a C/C++ toolchain
# and NOTHING of the benchmark (the ceb package is intentionally absent). At run
# time bench/ceb/track_b/build_jail.py mounts the source read-only at /src, a
# writable output dir at /out, and the trusted wrapper read-only at /wrapper.sh,
# always with --network none, read-only root + tmpfs /tmp, resource limits, and
# a non-root user. There is no network, so builds must be self-contained.
#
# This is functionally equivalent to chess-en-bench-jail:0.4; build_jail.py
# reuses that image by default. Build this dedicated image only if you want the
# build environment separated from the engine-run jail.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

CMD ["bash", "--version"]
