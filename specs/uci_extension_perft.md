# UCI Extension: `go perft <depth>`

A small benchmark-specific extension to the minimal UCI subset
(`specs/uci_minimal.md`) that lets the public gate verify your move
generator directly. It is **recommended, not mandatory**: the gate config
ships `perft_required: false` (`tracks/a_from_scratch/public/gate_config.yaml`).

Implementing it is strongly advised — a wrong move generator otherwise
only surfaces later as illegal-move faults in matches, which cost games
and penalty points.

## Command

```
go perft <depth>
```

`perft(depth)` is the number of leaf nodes of the legal-move tree at
exactly `<depth>` plies from the current position (set by the preceding
`position` command). Depth 1 equals the number of legal moves.

## Reply

Print **exactly one line**:

```
info string perft <nodes>
```

where `<nodes>` is the decimal node count, then return to idle (the gate
sends `isready` after each perft and expects `readyok`).

The parser (`bench/ceb/uci/protocol.py`) matches:

- `^info\s+string\s+perft\s+(\d+)\s*$` — the format this spec defines.
- `^Nodes searched:\s*(\d+)\s*$` — also tolerated, so a Stockfish-style
  reply (per-move lines followed by `Nodes searched: N`) works unchanged.
  Non-matching lines before the count are skipped.

Do not print a `bestmove` line in response to `go perft`.

## Gate behavior

The gate's `perft` check (`check_perft` in `bench/ceb/gate/gate_runner.py`)
runs every entry of `tracks/a_from_scratch/public/perft_examples.jsonl`
with `depth <= perft_max_depth` (default 3) and compares against
oracle-verified counts:

- **Unsupported -> WARN.** The engine is treated as not supporting the
  extension when it answers `go perft` with a `bestmove` line (i.e. it
  started a normal search), or when it produces no recognizable reply
  within 20 s (the harness then sends `stop` and drains any late
  `bestmove`). The check is marked `warn`; the gate still passes.
- **Wrong count -> FAIL.** Any node count that differs from the expected
  value fails the check, and a failed check fails the overall gate
  (`passed` requires every non-skipped, non-warn check to pass — see
  `bench/ceb/gate/reports.py`). Later checks still run so you get a full
  report.
- With `perft_required: true` in the gate config, unsupported would also
  fail; the shipped default is `false`.

Practical consequence: if you implement the extension, it must be correct.
Answering with made-up numbers is strictly worse than not implementing it.

## Sample transcript

`>` is harness to engine, `<` is engine to harness.

```
> uci
< id name MyEngine 0.1
< uciok
> isready
< readyok
> position fen rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1
> isready
< readyok
> go perft 2
< info string perft 400
> isready
< readyok
```

Startpos reference values (from the public examples file): depth 1 = 20,
depth 2 = 400, depth 3 = 8902.

## Testing locally

All test positions and expected counts are public:

```
cat tracks/a_from_scratch/public/perft_examples.jsonl
ceb gate run --track A --workspace <your-workspace>
```

The repository's oracle can generate reference counts for any position via
`bench/ceb/chess/perft.py` (`from ceb.chess import parse_fen;
from ceb.chess.perft import perft; perft(parse_fen(fen), depth)`).
