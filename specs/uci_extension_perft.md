# UCI Extension: `go perft <depth>`

A small benchmark-specific extension to the minimal UCI subset
(`specs/uci_minimal.md`) that lets the gate verify your move generator
directly. The requirement is two-tier:

- **Public gate** (`ceb gate run`, the default): recommended. Missing
  support is a `warn` — the gate still passes — but a wrong count is a
  `fail`. The shipped config has `perft_required: false`
  (`tracks/a_from_scratch/public/gate_config.yaml`).
- **Strict gate** (`ceb gate run --strict`; official rounds always run the
  strict gate before any game): REQUIRED. Missing support **or** a wrong
  count fails the gate, and a failing gate aborts the round without
  consuming budget. Without this extension you cannot play official rounds.

Beyond the gate, a wrong move generator surfaces as illegal-move faults in
matches, which cost games and penalty points — implement perft early.

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
runs every perft row of the resolved eval pack with `depth <=
perft_max_depth` (default 3) and compares against oracle-verified counts.
The public rows are `tracks/a_from_scratch/public/perft_examples.jsonl`;
strict (official-round) evaluations may add hidden rows from an
operator-mounted eval pack.

- **Unsupported -> WARN public, FAIL strict.** The engine is treated as not
  supporting the extension when it answers `go perft` with a `bestmove`
  line (i.e. it started a normal search), or when it produces no
  recognizable reply within 20 s (the harness then sends `stop` and drains
  any late `bestmove`). The strict gate forces `perft_required: true`
  (setting it in the gate config makes the public gate equally demanding).
- **Wrong count -> FAIL in both modes.** Any node count that differs from
  the expected value fails the check, and a failed check fails the overall
  gate (`passed` requires every non-skipped, non-warn check to pass — see
  `bench/ceb/gate/reports.py`).
- In the public gate, `perft` is a soft check: later checks still run so
  you get a full report. In strict mode it is a hard check — a failure
  skips the remaining checks. Failure details quote row ids only (e.g.
  `perft mismatch on hidden_perft_2 ...`), never FENs.

Practical consequence: implement the extension and make it correct.
Answering with made-up numbers is strictly worse than not implementing it —
and not implementing it caps you at the public gate and quick rounds.

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

All public test positions and expected counts are available:

```
cat tracks/a_from_scratch/public/perft_examples.jsonl
ceb gate run --track A --workspace <your-workspace> --strict
```

The repository's oracle can generate reference counts for any position via
`bench/ceb/chess/perft.py` (`from ceb.chess import parse_fen;
from ceb.chess.perft import perft; perft(parse_fen(fen), depth)`).
