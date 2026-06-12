"""Track B candidate scanner: diff whitelist plus content rules.

Combines the existing diff whitelist check with content rules over the
changed files: no NNUE/book/tablebase payloads, no harness fingerprinting,
no network/process syscalls introduced into search code, no symlinks, no
binary artifacts. Official Track B submissions are source/patch-only.
"""

import re
from pathlib import Path

from ceb import paths
from ceb.track_b.diff_policy import changed_files, check_diff, load_patterns

SEVERITY_FAIL = "fail"
SEVERITY_WARN = "warn"

_BINARY_SUFFIXES = {".nnue", ".bin", ".book", ".rtbw", ".rtbz", ".syzygy",
                    ".o", ".a", ".so", ".exe"}

_CONTENT_RULES = [
    ("harness-fingerprinting",
     re.compile(r"chess_en_bench|CEB_|BenchRandom|BenchAlphaBeta|ceb\.match"),
     "benchmark/harness fingerprinting reference"),
    ("network-syscall",
     re.compile(r"\b(socket\s*\(|connect\s*\(|curl_easy|getaddrinfo\s*\()"),
     "network usage introduced into engine source"),
    ("process-spawn",
     re.compile(r"\b(system\s*\(|popen\s*\(|execve?\s*\(|fork\s*\(\s*\))"),
     "process spawning introduced into engine source"),
    ("tablebase",
     re.compile(r"\b(syzygy|tbprobe|gaviota)\b", re.IGNORECASE),
     "tablebase probing reference"),
]


def scan_track_b(baseline_src, candidate_src, root=None):
    """Scan a Track B candidate tree against its baseline."""
    if root is None:
        root = paths.find_repo_root()
    baseline_src = Path(baseline_src).resolve()
    candidate_src = Path(candidate_src).resolve()
    findings = []

    def add(rule, severity, path, detail):
        findings.append({"rule": rule, "severity": severity,
                         "path": str(path), "detail": detail})

    track_dir = paths.track_dir("B", root)
    allowed = load_patterns(track_dir / "allowed_paths.txt")
    forbidden = load_patterns(track_dir / "forbidden_paths.txt")
    diff = check_diff(baseline_src, candidate_src, allowed, forbidden)
    for violation in diff["violations"]:
        add("diff-whitelist", SEVERITY_FAIL, violation["path"],
            "%s (%s)" % (violation["reason"], violation["change"]))

    changes = changed_files(baseline_src, candidate_src)
    touched = changes["added"] + changes["modified"]

    # Source/patch-only: added files are already whitelist violations, but
    # also reject binary payloads and symlinks anywhere in the candidate.
    for rel in sorted(touched):
        path = candidate_src / rel
        if Path(rel).suffix.lower() in _BINARY_SUFFIXES:
            add("binary-payload", SEVERITY_FAIL, rel,
                "binary/NNUE/book payload in a source-only submission")
            continue
        try:
            blob = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in blob[:4096]:
            add("binary-payload", SEVERITY_FAIL, rel,
                "binary content in a changed source file")
            continue
        text = blob.decode("utf-8", errors="replace")
        for rule, regex, description in _CONTENT_RULES:
            if regex.search(text):
                add(rule, SEVERITY_FAIL, rel, description)

    for path in sorted(candidate_src.rglob("*")):
        if path.is_symlink():
            rel = path.relative_to(candidate_src)
            add("symlink", SEVERITY_FAIL, rel,
                "symlinks are rejected in candidate trees")

    return {
        "schema": "ceb.scan.track_b/v1",
        "baseline": str(baseline_src),
        "candidate": str(candidate_src),
        "diff_check": diff,
        "findings": findings,
        "passed": diff["passed"] and not any(
            f["severity"] == SEVERITY_FAIL for f in findings),
    }
