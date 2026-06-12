#!/usr/bin/env bash
# Gate build step: (re)create the executable ./engine wrapper.
set -euo pipefail
cd "$(dirname "$0")"
cat > engine <<'EOF'
#!/usr/bin/env bash
exec python3 "$(dirname "$0")/engine.py"
EOF
chmod +x engine
echo "built ./engine"
