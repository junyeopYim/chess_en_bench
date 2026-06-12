"""Static scanner for Track A workspaces.

Flags submissions that try to escape the "from scratch, offline,
self-contained" rules: external chess libraries, engine binaries, network
use, process spawning, embedded books/tablebases, harness fingerprinting,
symlink escapes, and unexpected binaries. The scanner is a tripwire, not a
proof system — hosted evaluation combines it with the engine jail.
"""

import re
from pathlib import Path

SEVERITY_FAIL = "fail"
SEVERITY_WARN = "warn"

DEFAULT_MAX_FILE_BYTES = 2 * 1024 * 1024   # embedded book/table tripwire
DEFAULT_MAX_LINE_CHARS = 100_000

_CODE_SUFFIXES = {".py", ".sh", ".c", ".cc", ".cpp", ".h", ".hpp", ".rs",
                  ".go", ".js", ".ts", ".rb", ".pl"}
_BOOK_SUFFIXES = {".bin", ".book", ".polyglot", ".rtbw", ".rtbz", ".syzygy",
                  ".nnue", ".ctg", ".abk"}

# (rule id, regex, severity, description) over code-file text.
_TEXT_RULES = [
    ("external-chess-lib",
     re.compile(r"^\s*(import\s+chess\b|from\s+chess(\.[\w.]*)?\s+import)|python-chess",
                re.MULTILINE),
     SEVERITY_FAIL, "external chess library (python-chess)"),
    ("external-engine",
     re.compile(r"\b(stockfish|fairy-stockfish|lc0|leela|gnuchess|komodo|"
                r"ethereal|berserk)\b", re.IGNORECASE),
     SEVERITY_FAIL, "external engine reference"),
    ("network",
     re.compile(r"^\s*(import\s+(socket|requests|aiohttp|httpx)\b"
                r"|from\s+(socket|requests|aiohttp|httpx)\b"
                r"|import\s+urllib\b|from\s+urllib\b"
                r"|import\s+http\.client\b|from\s+http\.client\b)"
                r"|urllib\.request|http\.client\.HTTPConnection",
                re.MULTILINE),
     SEVERITY_FAIL, "network library usage"),
    ("process-spawn",
     re.compile(r"^\s*(import\s+subprocess\b|from\s+subprocess\b)"
                r"|os\.system\s*\(|os\.popen\s*\(|os\.exec[lv]p?e?\s*\("
                r"|subprocess\.(run|Popen|call|check_output)",
                re.MULTILINE),
     SEVERITY_FAIL, "process spawning"),
    ("harness-fingerprinting",
     re.compile(r"bench/ceb|CEB_PRIVATE_EVAL_DIR|CEB_SIGNING_KEY|eval_packs"
                r"|tracks/[ab]_[a-z_]+/private|ceb\.match\.opponents"),
     SEVERITY_FAIL, "benchmark-internal path or variable reference"),
]


def _is_binary(blob):
    return b"\x00" in blob[:4096] or blob[:4] in (b"\x7fELF", b"\xcf\xfa\xed\xfe",
                                                  b"\xca\xfe\xba\xbe")


def scan_workspace(workspace, max_file_bytes=DEFAULT_MAX_FILE_BYTES,
                   max_line_chars=DEFAULT_MAX_LINE_CHARS):
    """Scan a Track A workspace. Returns a JSON-serializable report."""
    workspace = Path(workspace).resolve()
    findings = []

    def add(rule, severity, path, detail):
        findings.append({"rule": rule, "severity": severity,
                         "path": str(path), "detail": detail})

    if not workspace.is_dir():
        add("workspace-missing", SEVERITY_FAIL, workspace,
            "workspace directory not found")
        return _report(workspace, findings)

    for path in sorted(workspace.rglob("*")):
        rel = path.relative_to(workspace)
        if any(part in (".git", "__pycache__") for part in rel.parts):
            continue
        if path.is_symlink():
            try:
                target = path.resolve()
                escaped = workspace not in target.parents and target != workspace
            except OSError:
                escaped = True
            if escaped:
                add("symlink-escape", SEVERITY_FAIL, rel,
                    "symlink points outside the workspace")
            else:
                add("symlink", SEVERITY_WARN, rel, "symlink inside workspace")
            continue
        if not path.is_file():
            continue

        size = path.stat().st_size
        suffix = path.suffix.lower()
        if suffix in _BOOK_SUFFIXES:
            add("book-or-tablebase", SEVERITY_FAIL, rel,
                "opening book / tablebase / network file extension")
            continue
        if size > max_file_bytes:
            add("oversized-file", SEVERITY_FAIL, rel,
                "file is %d bytes (limit %d): embedded table/book tripwire"
                % (size, max_file_bytes))
            continue

        try:
            blob = path.read_bytes()
        except OSError:
            add("unreadable", SEVERITY_WARN, rel, "could not read file")
            continue
        if _is_binary(blob):
            add("binary-artifact", SEVERITY_FAIL, rel,
                "binary artifact where source-only is expected")
            continue

        if suffix in _CODE_SUFFIXES or rel.name == "engine":
            text = blob.decode("utf-8", errors="replace")
            if any(len(line) > max_line_chars for line in text.splitlines()):
                add("oversized-line", SEVERITY_FAIL, rel,
                    "single line over %d chars: embedded table tripwire"
                    % max_line_chars)
            for rule, regex, severity, description in _TEXT_RULES:
                if regex.search(text):
                    add(rule, severity, rel, description)

    return _report(workspace, findings)


def _report(workspace, findings):
    return {
        "schema": "ceb.scan.workspace/v1",
        "workspace": str(workspace),
        "findings": findings,
        "fail_count": sum(1 for f in findings if f["severity"] == SEVERITY_FAIL),
        "warn_count": sum(1 for f in findings if f["severity"] == SEVERITY_WARN),
        "passed": not any(f["severity"] == SEVERITY_FAIL for f in findings),
    }
