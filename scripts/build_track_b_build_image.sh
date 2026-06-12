#!/usr/bin/env bash
# Build the dedicated Track B build-jail image (optional; build_jail.py reuses
# the engine jail image by default).
set -euo pipefail
cd "$(dirname "$0")/.."

IMAGE="${1:-chess-en-bench-build-jail:0.4}"

docker build -f infra/docker/track_b_build_jail.Dockerfile -t "$IMAGE" .

echo
echo "Built $IMAGE. Use it with build_in_jail(..., image=\"$IMAGE\")."
