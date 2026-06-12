#!/usr/bin/env bash
# Gate build step: compile engine.cpp into the executable ./engine.
set -euo pipefail
cd "$(dirname "$0")"
g++ -O2 -std=c++17 -o engine engine.cpp
chmod +x engine
echo "built ./engine"
