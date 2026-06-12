# Engine jail image for chess_en_bench.
# Build from the repo root:  bash scripts/build_jail_image.sh
#
# Contains a build toolchain so compiled-language submissions (C/C++/native via
# build.sh) and Python submissions can both build and run from source:
#   - Python 3, bash
#   - gcc / g++ / make (build-essential)
# and NOTHING of the benchmark. The ceb package is NOT installed here — a jailed
# engine must not be able to import evaluator code. The submission workspace is
# mounted at /submission by bench/ceb/jail/docker_engine.py: WRITABLE for the
# build step (build.sh produces ./engine), READ-ONLY for the engine run, always
# with --network none, --read-only root + tmpfs /tmp, resource limits, and a
# non-root user. There is no network at build OR run time, so submissions must
# be self-contained / from scratch.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

CMD ["python3", "--version"]
