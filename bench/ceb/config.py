"""Config loading for the benchmark's own YAML files.

To keep the core dependency-free, this implements a small YAML subset that
all configs in this repository conform to:

- comments (#) and blank lines
- nested mappings via 2-space indentation
- "key: value" scalars (str, int, float, bool, null)
- block lists of scalars ("- item") and inline lists ("[a, b, c]")

It is NOT a general YAML parser; third-party YAML will not round-trip.
"""

from pathlib import Path


def _parse_scalar(text):
    text = text.strip()
    if not text:
        return None
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part) for part in inner.split(",")]
    if (text.startswith('"') and text.endswith('"')) or \
       (text.startswith("'") and text.endswith("'")):
        return text[1:-1]
    low = text.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "none", "~"):
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def _strip_comment(line):
    # Good enough for our files: '#' starts a comment unless inside quotes.
    out = []
    in_quote = None
    for ch in line:
        if in_quote:
            out.append(ch)
            if ch == in_quote:
                in_quote = None
        elif ch in ("'", '"'):
            in_quote = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


def loads_simple_yaml(text):
    """Parse the YAML subset described in the module docstring into dicts/lists."""
    root = {}
    # stack of (indent, container)
    stack = [(-1, root)]
    pending_key = None  # key awaiting a nested block
    pending_indent = -1

    for raw in text.splitlines():
        line = _strip_comment(raw)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        content = line.strip()

        # Resolve pending nested block on first child line.
        if pending_key is not None:
            if indent > pending_indent:
                container = [] if content.startswith("- ") or content == "-" else {}
                parent = stack[-1][1]
                parent[pending_key] = container
                stack.append((indent, container))
            else:
                stack[-1][1][pending_key] = None
            pending_key = None

        # Pop levels deeper than the current indent.
        while len(stack) > 1 and indent < stack[-1][0]:
            stack.pop()

        container = stack[-1][1]

        if content.startswith("- ") or content == "-":
            if not isinstance(container, list):
                raise ValueError("list item outside a list context: %r" % raw)
            container.append(_parse_scalar(content[1:].strip()))
            continue

        if ":" not in content:
            raise ValueError("cannot parse line: %r" % raw)
        key, _, value = content.partition(":")
        key = key.strip()
        value = value.strip()
        if not isinstance(container, dict):
            raise ValueError("mapping entry inside a list: %r" % raw)
        if value == "":
            pending_key = key
            pending_indent = indent
        else:
            container[key] = _parse_scalar(value)

    if pending_key is not None:
        stack[-1][1][pending_key] = None
    return root


def load_simple_yaml(path):
    return loads_simple_yaml(Path(path).read_text(encoding="utf-8"))


def load_track_config(track, root=None):
    from ceb.paths import track_dir
    return load_simple_yaml(track_dir(track, root) / "track.yaml")


def load_scoring_config(track, root=None):
    from ceb.paths import track_dir
    return load_simple_yaml(track_dir(track, root) / "scoring.yaml")


def load_gate_config(root=None):
    from ceb.paths import track_dir
    return load_simple_yaml(track_dir("A", root) / "public" / "gate_config.yaml")
