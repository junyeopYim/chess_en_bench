#!/usr/bin/env bash
# Create the development virtualenv and install the project with extras.
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,server]"

echo
echo "Done. Activate with:  . .venv/bin/activate"
echo "Then try:             ceb doctor"
