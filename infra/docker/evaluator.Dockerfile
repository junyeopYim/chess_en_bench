# Evaluator image for chess_en_bench sandboxed runs.
# Build from the repo root:  bash scripts/build_evaluator_image.sh
#
# At runtime the live repo is mounted read-only at /bench (CEB_ROOT) and the
# submission workspace at /sandbox/workspace; this image only provides the
# Python runtime and the installed ceb package.

FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY bench ./bench
RUN pip install --no-cache-dir .

# The container is started with --user <host-uid>:<host-gid>, --network none,
# --read-only and resource limits by bench/ceb/sandbox/docker_runner.py.
CMD ["ceb", "doctor"]
