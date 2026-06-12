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
official round. Quick rounds (`--quick`) are free smoke evaluations. Games
start from a public opening suite — and official rounds may add hidden
openings — so your engine must play correctly from arbitrary positions, not
just lines you have seen. Round feedback is aggregate-only (W/D/L, score
rates, fault counts, scores) — no move logs, FENs, or opening ids.

## Task

Create a self-contained UCI chess engine in your workspace and maximize your
best official round score. Faults are penalized per occurrence: illegal move
−30, timeout −15, crash −25 points. Correctness first, strength second.

## Inputs

- Workspace (put your submission here): `runs/<run_id>/workspace/`
- UCI subset you must implement: `specs/uci_minimal.md`
- Perft extension, required for official rounds: `specs/uci_extension_perft.md`
- Public data: `tracks/a_from_scratch/public/` — `fen_examples.jsonl`,
  `perft_examples.jsonl`, `gate_config.yaml`, `openings_public.jsonl`
  (the opening suite; `openings_public.pgn` is the same lines for humans)
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
- **Official rounds REQUIRE `go perft <depth>`.** They run a strict gate where
  missing perft support or wrong node counts fail the gate, and a failed gate
  aborts the round. The default `ceb gate run` only warns when perft is
  missing; add `--strict` to preview the official policy.
- Games start from opening positions (both colors per opening), possibly
  including hidden ones — correct move generation everywhere (castling, en
  passant, promotion, pins) matters more than memorizing startpos lines.
- Do not read or modify benchmark code, runner state, or anything outside your
  workspace. No network access.
- Official round budget is 3; gate runs and quick rounds are unlimited.

## Iteration loop

1. Write a minimal correct engine (random legal mover is a valid start) and
   implement `go perft` early — it is mandatory for scoring and your best
   movegen debugging tool.
2. Run the gate and fix failures until it passes — this is free:
   `ceb gate run --track A --workspace runs/<run_id>/workspace`
3. Smoke-test strength for free with a quick round:
   `ceb round run --track A --workspace runs/<run_id>/workspace --round 1 --quick`
4. Improve search and evaluation (legal movegen → material eval → alpha-beta →
   move ordering → time management), re-running the gate after each change.
5. Only when the STRICT gate passes
   (`ceb gate run --track A --workspace runs/<run_id>/workspace --strict`)
   and quick-round results look strong, spend an official round:
   `ceb round run --track A --workspace runs/<run_id>/workspace --round 2`
6. Read `runs/<run_id>/round_N/feedback.json`, improve, and repeat. Keep at
   least one official round in reserve for your strongest version — your final
   score is the best valid official round, so a wasted round is never
   recoverable.

Do not run an official round before the strict gate passes: the round re-runs
the strict gate first and aborts (without consuming budget) if it fails, but
the attempt wastes your time.

## Output format

When you finish, the workspace must contain the final `engine` (or `build.sh`
that builds it) plus its sources. End with a short plain-text summary stating:

- which round number is your best official round and its final score,
- official budget used (out of 3),
- one paragraph describing your engine (movegen approach, search, eval).

## Acceptance criteria

- `ceb gate run --strict` exits 0 on the final workspace (all checks pass,
  including perft).
- At least one official round completed; `runs/<run_id>/state.json` records it.
- Zero candidate faults (illegal moves, timeouts, crashes) in the best round.
- The submission contains no external chess libraries or engines.
