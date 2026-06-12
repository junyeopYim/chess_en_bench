"""Opening suite loading and validation.

Canonical opening format is JSONL, one opening per line:

    {"id": "italian_001", "fen": "startpos", "moves": ["e2e4", ...], "tags": ["open"]}

`fen` is either the literal string "startpos" or a full FEN; `moves` are UCI
moves applied from that position. Every move is validated against the
internal oracle, so a corrupt suite fails loudly instead of silently
producing illegal starts. Legacy .pgn opening files are kept for human
readers but are not parsed by the runner.

Hidden suites: pass hidden=True so validation errors carry a sanitized
public message (row id + "content withheld") and keep the FEN/move detail
only on the private_message attribute for operator logs.
"""

import json
from pathlib import Path

from ceb.chess import START_FEN, parse_fen, board_to_fen, generate_legal, make_move, Move
from ceb.sanitize import SanitizedError


class OpeningError(SanitizedError, ValueError):
    """An opening row is malformed or contains an illegal move."""


def _raise(hidden, opening_id, category, detail):
    public = "opening %r: %s (content withheld)" % (opening_id, category)
    if hidden:
        raise OpeningError(public, "opening %r: %s: %s" % (opening_id, category, detail))
    raise OpeningError("opening %r: %s: %s" % (opening_id, category, detail))


def opening_start_fen(opening, hidden=False):
    """Resolve an opening row to its start FEN by applying its moves.

    Raises OpeningError on malformed rows or illegal moves; with hidden=True
    the exception's public message never includes FENs or moves.
    """
    opening_id = opening.get("id", "<unnamed>")
    fen = opening.get("fen", "startpos")
    if fen in (None, "", "startpos"):
        fen = START_FEN
    try:
        board = parse_fen(fen)
    except ValueError as exc:
        _raise(hidden, opening_id, "bad fen", exc)
    for uci in opening.get("moves") or []:
        try:
            move = Move.from_uci(uci)
        except ValueError as exc:
            _raise(hidden, opening_id, "bad move", exc)
        legal = {m.uci(): m for m in generate_legal(board)}
        if uci not in legal:
            _raise(hidden, opening_id, "illegal move",
                   "illegal move %r in position %s" % (uci, board_to_fen(board)))
        board = make_move(board, legal[uci])
    return board_to_fen(board)


def load_openings_jsonl(path, hidden=False):
    """Load and validate an opening suite file.

    Returns a list of {"id", "start_fen", "tags"} dicts, in file order.
    Raises OpeningError on any invalid row; FileNotFoundError if absent.
    With hidden=True, error public messages quote the file basename and row
    id only — never row contents.
    """
    path = Path(path)
    name = path.name if hidden else str(path)
    suite = []
    seen_ids = set()
    with open(path, encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise OpeningError("%s line %d: bad JSON" % (name, line_no),
                                   "%s line %d: bad JSON: %s" % (path, line_no, exc))
            if not isinstance(row, dict):
                raise OpeningError("%s line %d: row must be a JSON object"
                                   % (name, line_no))
            opening_id = row.get("id") or "opening_%d" % line_no
            if opening_id in seen_ids:
                raise OpeningError("%s line %d: duplicate opening id %r"
                                   % (name, line_no, opening_id))
            seen_ids.add(opening_id)
            suite.append({
                "id": opening_id,
                "start_fen": opening_start_fen(row, hidden=hidden),
                "tags": list(row.get("tags") or []),
                "hidden": bool(hidden),
            })
    if not suite:
        raise OpeningError("%s: opening suite is empty" % name)
    return suite


def rotate_suite(suite, pairs, offset):
    """Pick `pairs` openings starting at `offset` (wrapping).

    Used to spread a suite across opponents so an official round covers more
    openings than any single match plays.
    """
    if not suite:
        raise OpeningError("cannot rotate an empty opening suite")
    return [suite[(offset + k) % len(suite)] for k in range(pairs)]
