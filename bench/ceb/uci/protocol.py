"""UCI line parsing helpers (pure functions, no I/O)."""

import re

BESTMOVE_RE = re.compile(r"^bestmove\s+(\S+)")
ID_NAME_RE = re.compile(r"^id\s+name\s+(.+)$")
# Our perft extension reply (specs/uci_extension_perft.md) plus the
# Stockfish-style summary, both accepted.
PERFT_NODES_RES = (
    re.compile(r"^info\s+string\s+perft\s+(\d+)\s*$"),
    re.compile(r"^Nodes searched:\s*(\d+)\s*$"),
)


def parse_bestmove(line):
    """'bestmove e2e4 ponder e7e5' -> 'e2e4', else None."""
    m = BESTMOVE_RE.match(line.strip())
    return m.group(1) if m else None


def parse_id_name(line):
    m = ID_NAME_RE.match(line.strip())
    return m.group(1).strip() if m else None


def parse_perft_nodes(line):
    """Node count from a perft reply line, else None."""
    line = line.strip()
    for rx in PERFT_NODES_RES:
        m = rx.match(line)
        if m:
            return int(m.group(1))
    return None


def position_command(fen=None, moves=()):
    """Build a 'position ...' command string."""
    base = "position startpos" if fen is None else "position fen %s" % fen
    if moves:
        return base + " moves " + " ".join(moves)
    return base
