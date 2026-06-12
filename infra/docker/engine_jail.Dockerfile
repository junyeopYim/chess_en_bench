# Engine jail image for chess_en_bench.
# Build from the repo root:  bash scripts/build_jail_image.sh
#
# Deliberately minimal: a Python runtime and bash, NOTHING of the benchmark.
# The ceb package is NOT installed here — a jailed engine must not be able
# to import evaluator code. The submission workspace is mounted read-only at
# /submission by bench/ceb/jail/docker_engine.py with --network none,
# --read-only, tmpfs /tmp, resource limits, and a non-root user.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

CMD ["python3", "--version"]
