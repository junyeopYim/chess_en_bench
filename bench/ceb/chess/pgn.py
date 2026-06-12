"""Minimal PGN-like game text writer.

v0.1 writes movetext using UCI move strings (not SAN), which standard PGN
tools may not parse. The artifact is for human inspection and reproduction;
the JSON match report is the machine-readable record.
"""

from ceb.chess.board import START_FEN


def game_to_text(white_name, black_name, result, moves_uci, start_fen=START_FEN,
                 reason="", event="chess_en_bench"):
    """Render one game as PGN-style headers plus UCI movetext."""
    lines = [
        '[Event "%s"]' % event,
        '[White "%s"]' % white_name,
        '[Black "%s"]' % black_name,
        '[Result "%s"]' % result,
        '[MoveNotation "uci"]',
    ]
    if start_fen != START_FEN:
        lines.append('[SetUp "1"]')
        lines.append('[FEN "%s"]' % start_fen)
    if reason:
        lines.append('[Termination "%s"]' % reason)
    lines.append("")

    tokens = []
    for i, mv in enumerate(moves_uci):
        if i % 2 == 0:
            tokens.append("%d." % (i // 2 + 1))
        tokens.append(mv)
    tokens.append(result)

    # Wrap movetext at ~78 columns.
    out, line = [], ""
    for tok in tokens:
        if line and len(line) + 1 + len(tok) > 78:
            out.append(line)
            line = tok
        else:
            line = tok if not line else line + " " + tok
    if line:
        out.append(line)
    lines.extend(out)
    lines.append("")
    return "\n".join(lines)


def write_games_text(path, games):
    """Write a list of game-text blocks (from game_to_text) to a file."""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(games))
