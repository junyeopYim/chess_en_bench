"""Public-artifact leak scanner (P0.8).

Before a hosted official evaluation records a verified result, every PUBLIC
artifact it produced is mechanically checked against the secret tokens of the
private eval pack that was used. A public artifact must never contain:

  - a hidden FEN (full string or its placement field),
  - a hidden opening id or a hidden row id,
  - a hidden move sequence,
  - the private eval-pack directory path.

Tokens that are also part of the PUBLIC pack (legitimately public ids/FENs)
are excluded so a public-pack opening id appearing in a public report is not a
false positive. On any leak the official evaluation refuses to verify, the job
fails, and a private leak report (which never echoes the secret itself, only a
hash) is written.
"""

import hashlib
import json
from pathlib import Path

from ceb import paths
from ceb.storage import public_artifacts
from ceb.storage.artifacts import MANIFEST_NAME

SCHEMA = "ceb.scan.leak/v1"

_HIDDEN_FILES = ("fen_hidden.jsonl", "perft_hidden.jsonl", "openings_hidden.jsonl")
_PUBLIC_FILES = ("fen_examples.jsonl", "perft_examples.jsonl",
                 "openings_public.jsonl")
_MIN_TOKEN_LEN = 4
_ALWAYS_PUBLIC = {"startpos"}


def _placement(fen):
    """The piece-placement field of a FEN (the part that pins a position)."""
    if not isinstance(fen, str):
        return None
    head = fen.strip().split(" ", 1)[0]
    return head or None


def _add_row_tokens(tokens, row):
    if not isinstance(row, dict):
        return
    if row.get("id"):
        tokens.add(str(row["id"]))
    fen = row.get("fen")
    if isinstance(fen, str) and fen != "startpos":
        tokens.add(fen)
        placement = _placement(fen)
        if placement:
            tokens.add(placement)
    moves = row.get("moves")
    if isinstance(moves, list) and moves:
        joined = "".join(str(m) for m in moves)
        if len(joined) >= _MIN_TOKEN_LEN:
            tokens.add(joined)
        tokens.add(" ".join(str(m) for m in moves))


def _tokens_from_jsonl(path):
    tokens = set()
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return tokens
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            _add_row_tokens(tokens, json.loads(line))
        except json.JSONDecodeError:
            continue
    return tokens


def _public_tokens(root):
    public_dir = paths.track_dir("A", root) / "public"
    tokens = set()
    for name in _PUBLIC_FILES:
        tokens |= _tokens_from_jsonl(public_dir / name)
    return tokens


def collect_pack_secrets(private_dir, root=None):
    """Secret tokens that must never appear in any public artifact."""
    private_dir = Path(private_dir)
    secrets = set()
    for name in _HIDDEN_FILES:
        secrets |= _tokens_from_jsonl(private_dir / name)

    # Resolved start FENs of hidden openings (placement after moves applied).
    try:
        from ceb.match.openings import load_openings_jsonl
        for opening in load_openings_jsonl(private_dir / "openings_hidden.jsonl",
                                           hidden=True):
            placement = _placement(opening.get("start_fen"))
            if placement:
                secrets.add(placement)
                secrets.add(opening["start_fen"])
            if opening.get("id"):
                secrets.add(str(opening["id"]))
    except Exception:  # noqa: BLE001 - missing/invalid hidden openings are fine
        pass

    # The private pack directory PATH is sensitive (its basename is the pack's
    # public label and is intentionally not treated as secret).
    secrets.add(str(private_dir.resolve()))

    secrets -= _public_tokens(root)
    return {tok for tok in secrets
            if isinstance(tok, str) and len(tok) >= _MIN_TOKEN_LEN
            and tok not in _ALWAYS_PUBLIC}


def scan_text_for_leaks(text, secrets):
    """Return the list of secret tokens present in text (hashed, never echoed)."""
    return sorted(
        hashlib.sha256(tok.encode("utf-8")).hexdigest()[:12]
        for tok in secrets if tok in text)


def _artifacts_to_scan(out_dir, staged):
    """[(directory, name), ...] of the public-destined artifacts to leak-scan.

    staged=False: every artifact currently marked visibility=public.
    staged=True:  every artifact staged for public promotion (private now, with
                  a staged_public marker) — scanned BEFORE it is promoted."""
    if staged:
        from ceb.storage.promotion import staged_public_artifacts
        return staged_public_artifacts(out_dir)
    pairs = []
    for manifest_path in sorted(Path(out_dir).rglob(MANIFEST_NAME)):
        directory = manifest_path.parent
        for name in public_artifacts(directory):
            pairs.append((directory, name))
    return pairs


def scan_public_artifacts(out_dir, private_dir, root=None, *, staged=False):
    """Recursively scan public-destined artifacts under out_dir against the
    private pack secrets.

    The scan walks the whole tree, not just the top level, so it covers exactly
    the set the hosted worker registers and serves as public (e.g. nested
    round_<N>/report.public.json and feedback.json). With staged=True it scans
    the staged-public set instead, so the leak gate runs BEFORE promotion. A
    blind spot here would defeat the backstop. The report never contains the
    secret itself — only the artifact path and a short hash of each leaked token.
    """
    out_dir = Path(out_dir)
    secrets = collect_pack_secrets(private_dir, root)
    leaks = []
    scanned = []
    for directory, name in _artifacts_to_scan(out_dir, staged):
        path = directory / name
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            rel = path.relative_to(out_dir).as_posix()
        except ValueError:
            rel = name
        scanned.append(rel)
        hits = scan_text_for_leaks(text, secrets)
        if hits:
            leaks.append({"artifact": rel, "token_hashes": hits})
    return {
        "schema": SCHEMA,
        "secret_token_count": len(secrets),
        "staged": bool(staged),
        "public_artifacts_scanned": sorted(scanned),
        "leaks": leaks,
        "passed": not leaks,
    }
