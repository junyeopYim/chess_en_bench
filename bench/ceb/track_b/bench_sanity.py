"""Track B bench / speed sanity (v0.3.3, requirement 6).

For a verified Track B evaluation against real Stockfish, the baseline and
candidate should be exercised under consistent conditions and a deterministic
`bench` run recorded so the result captures node counts / NPS. Toy engines that
do not implement `bench` report supported=False; the caller then only enforces
the NPS-ratio threshold when both engines actually support bench.
"""

import hashlib
import re
import subprocess

SCHEMA = "ceb.track_b.bench_sanity/v1"
DEFAULT_MIN_NPS_RATIO = 0.3

# Match only the canonical Stockfish bench summary lines, anchored at the start
# of a (stripped) line with the ':' separator. This rejects trivially-spoofed
# lines like "info string Nodes/second 9e9". NOTE: a candidate's stdout is
# attacker-controlled, so bench NPS is a self-reported SANITY signal, not a
# security boundary — the real protections are the diff whitelist, the source
# scan, and running the candidate engine inside the engine jail.
_NODES_RE = re.compile(r"^Nodes\s+searched\s*:\s*(\d+)\b", re.IGNORECASE)
_NPS_RE = re.compile(r"^Nodes\s*/\s*second\s*:\s*(\d+)\b", re.IGNORECASE)


def run_bench(engine_cmd, *, timeout_s=120):
    """Run `bench` on one engine. Returns {supported, nodes, nps, output_hash}."""
    try:
        proc = subprocess.Popen(
            list(engine_cmd), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True)
    except OSError as exc:
        return {"supported": False, "nodes": None, "nps": None,
                "output_hash": None, "error": str(exc)[:120]}
    try:
        out, _ = proc.communicate("uci\nbench\nquit\n", timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            out, _ = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            out = ""
    nodes = nps = None
    for line in (out or "").splitlines():
        stripped = line.strip()
        m = _NODES_RE.match(stripped)
        if m:
            nodes = int(m.group(1))
        m = _NPS_RE.match(stripped)
        if m:
            nps = int(m.group(1))
    supported = nodes is not None or nps is not None
    return {
        "supported": supported,
        "nodes": nodes,
        "nps": nps,
        "output_hash": ("sha256:" + hashlib.sha256(out.encode("utf-8")).hexdigest()
                        if supported else None),
    }


def run_bench_sanity(baseline_cmd, candidate_cmd, *,
                     min_nps_ratio=DEFAULT_MIN_NPS_RATIO, timeout_s=120):
    """Run bench on baseline + candidate and compare. Returns a report dict.

    The TRUSTED baseline is the reference. `supported` reflects whether the
    baseline produced a bench NPS. When the baseline supports bench, the
    candidate MUST also produce a valid NPS at or above the ratio — a candidate
    that SUPPRESSES its bench output (no/zero NPS) gets ratio 0 and fails,
    closing the suppress-to-bypass hole. When the baseline does not support
    bench (toy engines), `supported` is False and `passed` stays True (the
    caller decides whether unsupported bench is acceptable)."""
    base = run_bench(baseline_cmd, timeout_s=timeout_s)
    cand = run_bench(candidate_cmd, timeout_s=timeout_s)
    baseline_supported = bool(base["supported"] and base["nps"])
    report = {
        "schema": SCHEMA,
        "baseline": base,
        "candidate": cand,
        "supported": baseline_supported,
        "min_nps_ratio": min_nps_ratio,
        "nps_ratio": None,
        "candidate_bench_missing": False,
        "passed": True,
    }
    if baseline_supported:
        cand_nps = cand["nps"]
        if cand_nps:
            ratio = cand_nps / base["nps"]
            report["nps_ratio"] = round(ratio, 4)
            report["passed"] = ratio >= min_nps_ratio
        else:
            report["candidate_bench_missing"] = True
            report["nps_ratio"] = 0.0
            report["passed"] = False  # baseline benches but candidate does not
    return report
