# Agent protocol (Track A)

This document is addressed to you, the evaluated agent. It defines the loop
you run, the inputs you get, the commands you may use, and the boundaries you
must respect. The deliverable contract for what goes inside the workspace is
in `specs/submission_contract.md`. Hard prohibitions are in
`specs/forbidden_behaviors.md` — read it before writing any code.

## What you receive

| Input | Location | Purpose |
|---|---|---|
| Task instructions | `runs/<run-id>/instructions.md` (copy of `tracks/a_from_scratch/prompt.md`) | what to build |
| Submission contract | `specs/submission_contract.md` | exact workspace/UCI requirements |
| Public FEN positions | `tracks/a_from_scratch/public/fen_examples.jsonl` | positions the gate tests `bestmove` legality on (castling, en passant, promotion, check evasion, endgames) |
| Public perft data | `tracks/a_from_scratch/public/perft_examples.jsonl` | exact node counts to validate your move generator |
| Public openings | `tracks/a_from_scratch/public/openings_public.pgn` | sample opening lines |
| Gate configuration | `tracks/a_from_scratch/public/gate_config.yaml` | the gate's timeouts and limits — fully public, no hidden thresholds in v0.1 |
| Gate report | printed summary + JSON (`ceb.gate.report/v1`), saved under `runs/_gate/` or `--json-out` | per-check pass/fail/warn/skip with details |
| Round feedback | `runs/<run-id>/round_N/feedback.json` (`ceb.round.feedback/v1`) | aggregate results after each round |

There is no hidden data in v0.1: `tracks/*/private/` directories are
documented placeholders.

## Commands you may run

```sh
ceb workspace prepare --track A --run-id <id>          # create runs/<id>/workspace
ceb gate run --track A --workspace <dir> [--json-out F] [--no-match]
ceb round run --track A --workspace <dir> --round N --quick   # free smoke round
ceb round run --track A --workspace <dir> --round N           # official (budgeted)
ceb doctor                                              # environment diagnosis
```

`ceb` is also runnable as `python -m ceb.cli`. You may freely read the public
track data and your own run artifacts under `runs/<run-id>/`. You must not
read or modify benchmark internals to influence scoring — see
`specs/forbidden_behaviors.md`.

## The loop: observe, modify, re-run the gate

1. Put your engine in the workspace: an executable `./engine`, or a
   `build.sh` that creates it (contract: `specs/submission_contract.md`).
2. Run the gate. It is free and unlimited — use it after every meaningful
   change:
   ```sh
   ceb gate run --track A --workspace runs/<id>/workspace --json-out gate.json
   ```
3. Read the report. Checks run in order — `format`, `build`, `engine`,
   `handshake`, `position`, `bestmove`, `perft`, `time`, `mini_match` — and a
   hard failure skips the rest, so fix the first `fail` first. Each check's
   `details` string says what went wrong (e.g. the FEN id and the illegal
   move it saw). Exit code 0 = passed, 2 = failed.
4. `perft` is the only soft check: missing `go perft` support is a `warn`
   (gate still passes), but a wrong node count is a `fail`. Validate your
   move generator against `perft_examples.jsonl` early — illegal-move bugs
   found later cost round budget.
5. When the gate passes, run a quick round (free, does not consume budget)
   to see real match results before spending an official round.

## Rounds and budget

- Budget: 3 official rounds per run. Quick rounds and gate runs are free.
- Quick mode: 2 opponents (BenchRandom, BenchMaterial1), 2 games each,
  movetime 50ms. Official mode: 6 opponents up to BenchAlphaBeta3, 4 games
  each, movetime 200ms.
- Every round re-runs the gate first; a failing gate aborts the round
  without consuming budget.
- Your final run score is the best valid round, so an early weak official
  round costs budget but never lowers your score.

## How feedback drives iteration

After each round you get sanitized, aggregate-only feedback
(`ceb.round.feedback/v1`): per-opponent W/D/L and score rates, fault counts,
penalty points, ladder/final score, and generic advice. You never get move
logs or private data — do not ask for them or try to reconstruct them.

Read it in this order:

1. **Faults first.** Penalties per candidate fault: illegal_move −30,
   timeout −15, crash −25 points, and each fault also loses that game.
   - `illegal`: re-check legality (castling rights, en passant, pins)
     against the public perft data.
   - `timeout`: respect `go movetime N` — always print a `bestmove` line
     within the budget, even if the search is unfinished.
   - `crash`: harden input parsing; never let an exception kill the process.
2. **Then strength.** With zero faults, per-opponent score rates show where
   you stand on the ladder (nominal ratings 400 → 1400). Losing to
   BenchMaterial1 (800) means material counting is missing; losing to
   BenchMiniMax2 (1200) means you need real search depth. Improving search
   and evaluation is the main lever for a higher ladder score.
3. Iterate against the gate and quick rounds; spend the next official round
   only when quick-round results clearly improve.

## What you must never do

`specs/forbidden_behaviors.md` is the authoritative list. In short: do not
import or shell out to benchmark code from your engine, do not call other
chess engines or libraries to produce moves, do not use the network, do not
read or tamper with benchmark internals, opponents, or scoring, and do not
target the evaluation harness instead of playing chess. The engine must be
self-contained and built by you from scratch. Violations invalidate the run.
