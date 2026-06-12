# Minimal UCI Subset (Track A submissions)

This is the exact UCI subset the benchmark harness uses. It is derived from
the code that talks to your engine: `bench/ceb/uci/client.py`,
`bench/ceb/uci/protocol.py`, `bench/ceb/gate/gate_runner.py`, and
`bench/ceb/match/internal_runner.py`. Implement everything below and your
engine will work with the gate and the match runner. Anything beyond this
subset (options, ponder, infinite search, MultiPV, ...) is never required.

Verify your implementation any time, for free:

```
ceb gate run --track A --workspace <your-workspace>
```

## Process model

- Your engine is spawned as `./engine` (argv only, no shell) with the
  workspace as its working directory.
- All communication is line-based text over stdin/stdout. Terminate lines
  with `\n` and flush stdout after every line (use line buffering).
- stderr is discarded; never put protocol output there.
- Output lines longer than 8192 characters are truncated, and the harness
  buffers at most 10000 pending lines. Keep search chatter modest;
  unbounded spam can block your own stdout writes.

## Required commands

| Harness sends | Engine must reply | Notes |
| --- | --- | --- |
| `uci` | lines ending with `uciok` | `id name <name>` is parsed and reported if present (recommended); other lines such as `id author` or `option ...` are ignored. |
| `isready` | `readyok` | Used as a sync barrier after the handshake, after `ucinewgame`, and after `position` commands. Must always work. |
| `ucinewgame` | nothing | Reset for a new game. Always followed by `isready`. |
| `position startpos` | nothing | Set the initial position. |
| `position fen <FEN>` | nothing | Set an arbitrary position (6-field FEN). |
| `position startpos moves <m1> <m2> ...` | nothing | Apply UCI moves after the base position. Also sent as `position fen <FEN> moves ...`. |
| `go movetime <ms>` | `bestmove <move>` | Search for roughly `<ms>` milliseconds, then print exactly one `bestmove` line. |
| `quit` | exit | Terminate promptly. |

Details:

- The harness ignores every line before `bestmove` (e.g. `info depth 3
  score cp 21`), so info output is allowed but never required.
- `bestmove e2e4 ponder e7e5` is accepted; only the first token after
  `bestmove` is used.
- During matches the harness re-sends the **full** position before every
  move: `position startpos moves <all moves so far>` followed by
  `go movetime <ms>`. Your `moves` handling must therefore be correct and
  reasonably fast for long move lists.
- `stop` may be sent if the harness gives up waiting (currently only in the
  perft check, see `specs/uci_extension_perft.md`). Honoring it with a
  prompt `bestmove` makes recovery cleaner; ignoring it is not a gate
  failure by itself.

## Move format

Moves are pure coordinate notation, as produced and parsed by
`bench/ceb/chess/move.py`:

- 4 characters `from`+`to` (`e2e4`, `g8f6`), or 5 with a promotion piece.
- Promotion piece is lowercase, one of `q r b n`: `e7e8q`.
- Castling is the king's two-file move: `e1g1`, `e1c1`, `e8g8`, `e8c8`.
- En passant is the capturing pawn's diagonal move to the en-passant
  square (e.g. `e5f6` when the FEN ep field is `f6`).
- There is no null move. Every `bestmove` is validated against the
  internal oracle; an illegal move fails the gate's bestmove check and, in
  matches, loses the game as an `illegal` fault (penalized in scoring).

## Timing expectations

Defaults from `tracks/a_from_scratch/public/gate_config.yaml` (the file is
public; read it for current values):

- Handshake: `uciok` and then `readyok` each within 8 s of the
  corresponding command.
- `go movetime T`: the harness waits `T + grace` for `bestmove`
  (grace 3000 ms in the gate's bestmove check and in matches).
  Missing the window is a gate failure or, in matches, a `timeout` fault
  (loss plus a score penalty).
- Dedicated time check: `go movetime 100` must return within a total
  budget of `100 + 2500` ms.
- The gate exercises movetimes as low as 50 ms (mini match). Returning any
  legal move quickly always beats searching past the deadline.
- On `quit` you get about 1.5 s to exit before the harness escalates to
  SIGTERM and then SIGKILL of the whole process group.

## Sample transcript

`>` is harness to engine, `<` is engine to harness.

```
> uci
< id name MyEngine 0.1
< id author Example
< uciok
> isready
< readyok
> ucinewgame
> isready
< readyok
> position startpos moves e2e4 e7e5
> go movetime 100
< info depth 3 score cp 21
< bestmove g1f3
> position fen r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1
> isready
< readyok
> go movetime 200
< bestmove e1g1
> quit
```

You can test interactively by running `./engine` in a terminal and typing
the harness side by hand, or compare against a benchmark opponent:
`python -m ceb.match.opponents BenchRandom` speaks the same subset.
