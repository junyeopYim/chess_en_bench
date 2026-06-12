#!/usr/bin/env bash
# Run the public Track A gate on a workspace (default: the bundled example).
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .venv/bin/activate ]; then
    . .venv/bin/activate
fi

WORKSPACE="${1:-examples/submissions/minimal_uci_engine_python}"
exec ceb gate run --track A --workspace "$WORKSPACE"
