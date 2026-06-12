"""Trusted Track B build-wrapper resolution (v0.3.2, section C).

The trusted build wrapper is operator-controlled and must live OUTSIDE the
candidate and baseline source trees, so a candidate can never supply its own
build logic for a verified evaluation. This module validates a wrapper path and
ships a tiny demo wrapper used by tests and local diagnostics.
"""

from pathlib import Path

from ceb.sanitize import SanitizedError

# A tiny demo wrapper: copies the (read-only) source into the writable output
# dir and produces an engine. It mirrors the toy fake Track B trees used in
# tests; real operators supply a wrapper that builds pinned Stockfish.
DEMO_WRAPPER = """\
#!/usr/bin/env bash
# Trusted demo build wrapper: build <src_ro> into <out> producing <engine>.
set -euo pipefail
SRC="$1"; OUT="$2"; ENGINE="$3"
cp -a "$SRC"/. "$OUT"/
cd "$OUT"
if [ -f "$OUT/engine.cpp" ]; then
  g++ -O2 -std=c++17 -o "$ENGINE" "$OUT/engine.cpp"
elif [ -f "$OUT/engine.py" ]; then
  cat > "$ENGINE" <<EOF
#!/usr/bin/env bash
exec python3 "\\$(dirname "\\$0")/engine.py"
EOF
else
  echo "demo wrapper: no engine.cpp or engine.py in source" >&2
  exit 2
fi
chmod +x "$ENGINE"
"""


class BuildWrapperError(SanitizedError, ValueError):
    pass


def _is_within(path, parent):
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
        return True
    except ValueError:
        return False


def validate_build_wrapper(wrapper_path, *, candidate_src=None, baseline_src=None):
    """Validate a trusted build wrapper. Returns the resolved Path.

    Rejects a wrapper that does not exist, is not a regular file, or lives
    inside the candidate/baseline source trees (which would let a candidate
    control its own verified build)."""
    if not wrapper_path:
        raise BuildWrapperError(
            "verified Track B requires a trusted --build-wrapper outside the "
            "candidate tree")
    wrapper = Path(wrapper_path)
    if not wrapper.is_file():
        raise BuildWrapperError("trusted build wrapper not found",
                                "build wrapper not found: %s" % wrapper)
    for label, tree in (("candidate", candidate_src), ("baseline", baseline_src)):
        if tree and _is_within(wrapper, tree):
            raise BuildWrapperError(
                "trusted build wrapper must live OUTSIDE the %s source tree; a "
                "candidate may not supply its own build logic" % label)
    return wrapper.resolve()


def write_demo_wrapper(path):
    """Write the demo build wrapper (tests / local diagnostics) and chmod +x."""
    path = Path(path)
    path.write_text(DEMO_WRAPPER, encoding="utf-8")
    path.chmod(0o755)
    return path
