"""Evaluation pack loading: public data plus optional operator-mounted
hidden packs.

A pack bundles the data an evaluation consumes:
  - fens:     bestmove-legality positions  (rows: {"id", "fen", "tags"})
  - perft:    perft expectations           (rows: {"id", "fen", "depth", "nodes"})
  - openings: validated opening suite      (rows: {"id", "start_fen", "tags"})

The public pack comes from tracks/a_from_scratch/public/. A private pack is
a directory (CLI --eval-pack or env CEB_PRIVATE_EVAL_DIR) containing any of:

    fen_hidden.jsonl       same row format as fen_examples.jsonl
    perft_hidden.jsonl     same row format as perft_examples.jsonl
    openings_hidden.jsonl  same row format as openings_public.jsonl
    manifest.json          optional: {"name": ..., "openings_mode": "extend"|"replace"}

Private packs extend the public data (openings may replace it via the
manifest). Real hidden data is never committed to this repository; see
examples/eval_packs/tiny_private/ for the documented shape. Rows in private
files are always assigned ids so reports and feedback never need to quote a
hidden FEN.
"""

import json
import os
from pathlib import Path

from ceb import paths
from ceb.chess import parse_fen
from ceb.match.openings import load_openings_jsonl
from ceb.sanitize import SanitizedError

ENV_PRIVATE_DIR = "CEB_PRIVATE_EVAL_DIR"

PRIVATE_FILES = {
    "fens": "fen_hidden.jsonl",
    "perft": "perft_hidden.jsonl",
    "openings": "openings_hidden.jsonl",
}


class EvalPackError(SanitizedError, ValueError):
    """Eval pack directory or contents are invalid.

    public_message never includes hidden FENs, moves, or paths beyond a
    basename; private_message carries operator detail.
    """


class EvalPack:
    def __init__(self, name, source, fens, perft, openings):
        self.name = name
        self.source = source        # "public" | "public+private"
        self.fens = fens
        self.perft = perft
        self.openings = openings

    def describe(self):
        return {
            "name": self.name,
            "source": self.source,
            "fens": len(self.fens),
            "perft": len(self.perft),
            "openings": len(self.openings),
        }


def _load_jsonl(path, id_prefix, hidden=False):
    path = Path(path)
    name = path.name if hidden else str(path)
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EvalPackError(
                    "%s line %d: bad JSON (content withheld)" % (name, line_no),
                    "%s line %d: bad JSON: %s" % (path, line_no, exc))
            if not isinstance(row, dict):
                raise EvalPackError("%s line %d: row must be a JSON object"
                                    % (name, line_no))
            row.setdefault("id", "%s_%d" % (id_prefix, line_no))
            if hidden:
                row["hidden"] = True
            # Validate FENs at load time. The error quotes the row id only —
            # never the FEN — so a typo in a hidden pack cannot leak the
            # position into any report or console output.
            if "fen" in row:
                try:
                    parse_fen(row["fen"])
                except (ValueError, TypeError):
                    raise EvalPackError(
                        "%s: row %r has an invalid FEN (content withheld)"
                        % (path.name, row["id"]),
                        "%s: row %r has an invalid FEN: %r"
                        % (path, row["id"], row.get("fen")))
            rows.append(row)
    return rows


def load_public_pack(root=None):
    """The public Track A data pack."""
    public = paths.track_dir("A", root) / "public"
    return EvalPack(
        name="public",
        source="public",
        fens=_load_jsonl(public / "fen_examples.jsonl", "fen"),
        perft=_load_jsonl(public / "perft_examples.jsonl", "perft"),
        openings=load_openings_jsonl(public / "openings_public.jsonl"),
    )


def load_private_pack_dir(private_dir):
    """Validate and load a private pack directory's raw pieces."""
    private_dir = Path(private_dir)
    if not private_dir.is_dir():
        raise EvalPackError(
            "eval pack directory %r not found (pass --eval-pack <dir> or set "
            "%s to a directory containing %s)"
            % (private_dir.name, ENV_PRIVATE_DIR, ", ".join(PRIVATE_FILES.values())),
            "eval pack directory not found: %s" % private_dir)
    pieces = {}
    fen_path = private_dir / PRIVATE_FILES["fens"]
    if fen_path.is_file():
        pieces["fens"] = _load_jsonl(fen_path, "hidden_fen", hidden=True)
    perft_path = private_dir / PRIVATE_FILES["perft"]
    if perft_path.is_file():
        pieces["perft"] = _load_jsonl(perft_path, "hidden_perft", hidden=True)
    openings_path = private_dir / PRIVATE_FILES["openings"]
    if openings_path.is_file():
        pieces["openings"] = load_openings_jsonl(openings_path, hidden=True)
    if not pieces:
        raise EvalPackError(
            "eval pack %r contains none of: %s"
            % (private_dir.name, ", ".join(PRIVATE_FILES.values())),
            "eval pack %s contains none of: %s"
            % (private_dir, ", ".join(PRIVATE_FILES.values())))
    manifest = {}
    manifest_path = private_dir / "manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise EvalPackError(
                "%s: bad manifest.json (content withheld)" % private_dir.name,
                "%s: bad manifest.json: %s" % (private_dir, exc))
        if not isinstance(manifest, dict):
            raise EvalPackError("%s: manifest.json must be a JSON object"
                                % private_dir.name)
    return pieces, manifest


def resolve_eval_pack(root=None, private_dir=None, allow_env=False):
    """Resolve the pack for an evaluation.

    private_dir: explicit private pack directory (CLI flag), or None.
    allow_env: when True (official/strict evaluation), fall back to the
    CEB_PRIVATE_EVAL_DIR environment variable. Public gate attempts pass
    allow_env=False so hidden data is never consumed unless requested.
    """
    pack = load_public_pack(root)
    if private_dir is None and allow_env:
        private_dir = os.environ.get(ENV_PRIVATE_DIR) or None
    if private_dir is None:
        return pack
    pieces, manifest = load_private_pack_dir(private_dir)
    openings = pack.openings
    if "openings" in pieces:
        if manifest.get("openings_mode", "extend") == "replace":
            openings = pieces["openings"]
        else:
            openings = pack.openings + pieces["openings"]
    return EvalPack(
        name=str(manifest.get("name", Path(private_dir).name)),
        source="public+private",
        fens=pack.fens + pieces.get("fens", []),
        perft=pack.perft + pieces.get("perft", []),
        openings=openings,
    )
