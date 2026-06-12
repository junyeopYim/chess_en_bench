# Track A agent prompt — build a UCI chess engine from scratch

This prompt is handed verbatim to the evaluated agent. `ceb workspace prepare`
copies it to `runs/<run_id>/instructions.md`. Angle-bracket fields such as
`<run_id>` are filled in by the operator before the run starts.

## Role

You are a coding agent being evaluated on the chess_en_bench benchmark,
Track A. You write all code yourself inside your workspace. You interact with
the benchmark only through the `ceb` CLI commands listed below.

## Context

The benchmark scores a chess engine you build by playing it against a ladder
of six fixed opponents (BenchRandom 400 … BenchAlphaBeta3 1400 nominal Elo).
A public correctness gate may be run **unlimited** times for free. Official
scored rounds are budgeted: **3 per run**, and your final score is your best
round. Quick rounds (`--quick`) are free smoke evaluations. Round feedback is
aggregate-only (W/D/L, score rates, fault counts, scores) — no move logs.

## Task

Create a self-contained UCI chess engine in your workspace and maximize your
best official round score. Faults are penalized per occurrence: illegal move
−30, timeout −15, crash −25 points. Correctness first, strength second.

## Inputs

- Workspace (put your submission here): `runs/<run_id>/workspace/`
- UCI subset you must implement: `specs/uci_minimal.md`
- Recommended perft extension: `specs/uci_extension_perft.md`
- Public data: `tracks/a_from_scratch/public/` — `fen_examples.jsonl`,
  `perft_examples.jsonl`, `gate_config.yaml`, `openings_public.pgn`
- Rules and scoring details: `docs/track_a_from_scratch.md`,
  `tracks/a_from_scratch/scoring.yaml`

## Constraints

- **From scratch.** Implement board representation, move generation, legality,
  and search yourself. No external chess libraries, engine binaries, opening
  books, or tablebases (e.g. python-chess, Stockfish) in the submission.
- The workspace must contain an executable `engine`, or a `build.sh` that
  produces `./engine` in under 120 seconds.
- The engine must answer `uci`, `isready`, `ucinewgame`, `position`, and
  `go movetime N` — always replying `bestmove <uci>` within the movetime plus
  a small grace. Never print a bestmove for an illegal move; never crash on
  unknown input.
- Implementing `go perft <depth>` is recommended (the gate only warns if it is
  missing, but fails on wrong counts).
- Do not read or modify benchmark code, runner state, or anything outside your
  workspace. No network access.
- Official round budget is 3; gate runs and quick rounds are unlimited.

## Iteration loop

1. Write a minimal correct engine (random legal mover is a valid start).
2. Run the gate and fix failures until it passes — this is free:
   `ceb gate run --track A --workspace runs/<run_id>/workspace`
3. Smoke-test strength for free with a quick round:
   `ceb round run --track A --workspace runs/<run_id>/workspace --round 1 --quick`
4. Improve search and evaluation (legal movegen → material eval → alpha-beta →
   move ordering → time management), re-running the gate after each change.
5. Only when the gate passes and quick-round results look strong, spend an
   official round:
   `ceb round run --track A --workspace runs/<run_id>/workspace --round 2`
6. Read `runs/<run_id>/round_N/feedback.json`, improve, and repeat. Keep at
   least one official round in reserve for your strongest version — your final
   score is the best valid round, so a wasted round is never recoverable.

Do not run an official round before the gate passes: the round re-runs the
gate first and aborts (without consuming budget) if it fails, but the attempt
wastes your time.

## Output format

When you finish, the workspace must contain the final `engine` (or `build.sh`
that builds it) plus its sources. End with a short plain-text summary stating:

- which round number is your best official round and its final score,
- official budget used (out of 3),
- one paragraph describing your engine (movegen approach, search, eval).

## Acceptance criteria

- `ceb gate run` exits 0 on the final workspace (all hard checks pass).
- At least one official round completed; `runs/<run_id>/state.json` records it.
- Zero candidate faults (illegal moves, timeouts, crashes) in the best round.
- The submission contains no external chess libraries or engines.
