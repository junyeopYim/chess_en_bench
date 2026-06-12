#!/usr/bin/env bash
# Build the Docker evaluator image used by `ceb ... --sandbox docker`.
set -euo pipefail
cd "$(dirname "$0")/.."

IMAGE="${1:-chess-en-bench-evaluator:0.2}"

docker build -f infra/docker/evaluator.Dockerfile -t "$IMAGE" .

echo
echo "Built $IMAGE. Try:"
echo "  ceb gate run --track A --workspace examples/submissions/minimal_uci_engine_python --sandbox docker"
