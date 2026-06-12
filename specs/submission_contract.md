# Submission contract (Track A workspace)

This is the binding contract between a submission workspace and the
benchmark harness. The gate (`ceb gate run`) enforces it mechanically; rounds
re-run the gate before any match. Behavioral prohibitions are in
`specs/forbidden_behaviors.md`. A reference submission that satisfies this
contract lives in `examples/submissions/minimal_uci_engine_python/`.

## Workspace layout

The workspace directory MUST contain at least one of:

- `./engine` — an executable file that speaks UCI (see below), or
- `./build.sh` — a script that creates `./engine`.

Anything else in the workspace (sources, data files) is yours; the harness
only ever executes `build.sh` and `engine`.

## build.sh

- Run as `bash build.sh` with `cwd` = the workspace directory, output
  captured, **120-second timeout**. Exceeding it or exiting non-zero fails
  the `build` check (the last 300 characters of stderr/stdout are reported).
- If `build.sh` is absent, the check passes as "prebuilt engine".
- After the build, `./engine` must exist as a regular file. If it lacks the
  execute bit the harness attempts a `chmod +x`; set it yourself rather than
  relying on that.
- `engine` may be any executable: a native binary, or a wrapper script that
  `exec`s an interpreter (the example wraps `python3 engine.py`).

## Execution environment

- The engine is spawned argv-only — `[<workspace>/engine]`, never through a
  shell — with `cwd` = the workspace. Use paths relative to the workspace or
  resolve them from `$0` / `argv[0]`.
- stdin/stdout carry UCI text, line-buffered. **Flush stdout after every
  reply** — an unflushed `bestmove` is indistinguishable from a timeout.
- stderr is discarded; lines longer than 8192 characters are truncated.
- On shutdown the harness sends `quit`, then SIGTERM/SIGKILL to the whole
  process group. Do not spawn processes that must outlive the engine.
- The engine MUST be self-contained: no imports of the `ceb` package or any
  other benchmark code, no network access, no reading benchmark internals.
  It must run with nothing but the workspace and a stock interpreter or its
  own statically available dependencies.

## Required UCI subset

| You receive | You must reply | Deadline |
|---|---|---|
| `uci` | `id name <name>` (recommended), then `uciok` | 8s to `uciok` |
| `isready` | `readyok` | 8s to `readyok` |
| `ucinewgame` | nothing (reset state) | next `isready` must still get `readyok` |
| `position startpos [moves ...]` | nothing | — |
| `position fen <FEN> [moves ...]` | nothing | — |
| `go movetime N` | `bestmove <uci-move>` | **N + grace ms** (grace 3000ms default) |
| `setoption name <x> value <y>` | nothing | must be tolerated, never crash (matches send `setoption name Seed value <n>`) |
| `quit` | exit | ~1.5s before SIGTERM |

Timeouts come from `tracks/a_from_scratch/public/gate_config.yaml`. The gate
uses movetime 200ms + 3000ms grace for the bestmove check, and a stricter
dedicated time check: `go movetime 100` must produce `bestmove` within
100 + 2500ms. Treat `go movetime N` as a hard budget: always emit a
`bestmove` line by the deadline, even if the search is unfinished.

Moves use UCI long algebraic notation (`e2e4`, `e7e8q`, castling as the king
move `e1g1`). Every `bestmove` must be legal in the current position — the
harness validates each one against its internal oracle.

## Match-time behavior

- Before every move the harness re-sends the full position
  (`position startpos moves <all moves so far>` or `position fen ... moves
  ...`), then `go movetime N`. Do not rely on incremental state.
- The harness never asks for a move in a terminal position; games end at
  checkmate, stalemate, the fifty-move rule, or max-plies adjudication.
  Replying `bestmove 0000` when you have no legal moves is an accepted
  safety convention (see the example engine), never required.
- Faults end the game as a loss and are penalized in the round score:
  illegal move (−30 points), timeout (−15), crash/EOF on stdout (−25).

## Optional: `go perft <depth>` extension

Strongly recommended (the gate warns when missing, and fails only on wrong
counts). On `go perft D`, reply with one line:

    info string perft <nodes>

(the Stockfish-style `Nodes searched: <nodes>` is also accepted). Details in
`specs/uci_extension_perft.md`; expected counts for public positions are in
`tracks/a_from_scratch/public/perft_examples.jsonl` (gate checks depth ≤ 3).

## Verifying compliance

```sh
ceb gate run --track A --workspace <dir> --json-out gate.json   # exit 0 = pass
ceb gate run --track A --workspace <dir> --no-match             # skip mini match
```

The gate is unlimited and never consumes round budget. Checks run in order
(format, build, engine, handshake, position, bestmove, perft, time,
mini match vs BenchRandom); the report (`ceb.gate.report/v1`) names the first
failing check with details. Counterexamples that fail this contract are in
`examples/submissions/broken_engine_examples/`.
