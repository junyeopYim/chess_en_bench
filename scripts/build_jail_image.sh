#!/usr/bin/env bash
# Build the engine-jail Docker image used by `ceb ... --engine-jail docker`.
set -euo pipefail
cd "$(dirname "$0")/.."

IMAGE="${1:-chess-en-bench-jail:0.4}"

docker build -f infra/docker/engine_jail.Dockerfile -t "$IMAGE" .

echo
echo "Built $IMAGE. Try:"
echo "  ceb gate run --track A --workspace examples/submissions/minimal_uci_engine_python --engine-jail docker"
