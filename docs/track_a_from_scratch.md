# Track A — from-scratch chess engine

Track A measures whether an agent can build a working UCI chess engine without
external chess libraries, then improve it against a fixed opponent ladder.
Everything described here is implemented in v0.1 and runs locally with no
hidden data (`tracks/a_from_scratch/private/` is a documented placeholder).
Track config: `tracks/a_from_scratch/track.yaml` (3 official rounds per run,
unlimited gate attempts, final score = best valid round).

## From-scratch requirement

The submission must implement its own chess logic: board representation, move
generation, legality, and search. External chess libraries and engines are
forbidden in the submission — no python-chess, no Stockfish bindings, no
downloaded engine binaries, opening books, or tablebases. Any language is
acceptable as long as the workspace yields a runnable `./engine`.

v0.1 enforces this behaviorally (every move is validated by the benchmark's
own oracle in `bench/ceb/chess/`; perft counts are cross-checked) and by
inspection of the workspace. There is no automated library scanner yet.

## Submission layout

A workspace needs one of:

- `engine` — executable speaking the UCI subset in `specs/uci_minimal.md`, or
- `build.sh` — script (120 s limit) that produces `./engine`; the gate runs it.

```bash
ceb workspace prepare --track A --run-id myrun    # creates runs/myrun/workspace
```

A working reference: `examples/submissions/minimal_uci_engine_python/`.

## The public gate (unlimited attempts)

```bash
ceb gate run --track A --workspace runs/myrun/workspace [--json-out F] [--no-match]
```

The gate never consumes round budget. Checks run in order; a hard failure
skips the remaining heavy checks. Exit code 0 on pass, 2 on fail. The JSON
report (schema `ceb.gate.report/v1`) is saved under `runs/_gate/` unless
`--json-out` is given.

| # | Check | Verifies | Severity |
| --- | --- | --- | --- |
| 1 | format | `engine` or `build.sh` present in the workspace | hard |
| 2 | build | `build.sh` exits 0 within 120 s (skipped if prebuilt) | hard |
| 3 | engine | `./engine` exists and is executable | hard |
| 4 | handshake | `uci`/`uciok`, `isready`/`readyok` | hard |
| 5 | position | `position startpos` / `fen ...` / `moves ...` accepted | hard |
| 6 | bestmove | legal bestmove on the public FENs, oracle-validated | hard |
| 7 | perft | `go perft` counts match the oracle (depth ≤ 3) | soft |
| 8 | time | bestmove for `go movetime 100` within a 2500 ms budget | hard |
| 9 | mini_match | 2 games vs BenchRandom at 50 ms/move, zero candidate faults | hard |

Perft is the one soft check: the `go perft` extension
(`specs/uci_extension_perft.md`) is RECOMMENDED — missing support only warns,
but wrong node counts fail the gate. All tunables (timeouts, movetimes,
mini-match size) are public in `tracks/a_from_scratch/public/gate_config.yaml`:
handshake timeout 8 s, bestmove movetime 200 ms + 3000 ms grace, at most 2
bestmove failures reported.

## Round modes

```bash
ceb round run --track A --workspace runs/myrun/workspace --round 1 --quick   # free
ceb round run --track A --workspace runs/myrun/workspace --round 2           # spends budget
```

Every round re-runs the gate first; a failing gate aborts the round without
consuming budget. From `tracks/a_from_scratch/scoring.yaml`:

| Mode | Opponents | Games each | movetime | max plies | Budget |
| --- | --- | --- | --- | --- | --- |
| quick | BenchRandom, BenchMaterial1 | 2 | 50 ms | 120 | free |
| official | all six (ladder order below) | 4 | 200 ms | 200 | 1 of 3 per run |

The internal runner (`bench/ceb/match/internal_runner.py`) alternates colors,
seeds each game, validates every move against the oracle, and adjudicates
draws at the ply cap and via the fifty-move rule. Artifacts land in
`runs/<run_id>/round_N/`: per-opponent `match_vs_*.json`, UCI-movetext game
files, `report.json` (`ceb.round.report/v1`), and `feedback.json`
(`ceb.round.feedback/v1`) — aggregate-only: per-opponent W/D/L and score
rates, fault counts, scores, generic advice. No move logs are fed back.

## Opponent pool

Benchmark-owned, deterministic given a seed (set per game by the runner), and
runnable standalone: `python -m ceb.match.opponents BenchRandom`.

| Name | Nominal rating | Move selection |
| --- | --- | --- |
| BenchRandom | 400 | uniform random legal move |
| BenchGreedyCapture | 600 | highest-value capture if any (incl. en passant), else random |
| BenchMaterial1 | 800 | depth-1 negamax, material-only eval |
| BenchPST1 | 1000 | depth-1 negamax, material + center/pawn-advance square bonuses |
| BenchMiniMax2 | 1200 | depth-2 negamax, material-only eval |
| BenchAlphaBeta3 | 1400 | depth-3 alpha-beta, material + square bonuses |

Depth-based opponents iteratively deepen within `go movetime` and fall back to
the deepest completed depth; ties between equal moves break via the seeded RNG.

## Scoring summary

Per opponent (`bench/ceb/scoring/elo.py`, `bench/ceb/scoring/track_a.py`):

- `score_rate = (W + 0.5·D) / games`, clamped into (0, 1) by `eps = 1 / (2·(games+1))`
- `delta_elo = −400 · log10(1/rate − 1)`
- `performance = opponent_rating + delta_elo`

`ladder_score` = mean performance across opponents. Penalty per candidate
fault: illegal_move 30, timeout 15, crash 25 points. Round
`final_score = ladder_score − penalties` (schema `ceb.score.track_a/v1`). The
run's score is its **best valid round**; rank runs with:

```bash
ceb leaderboard compute --track A --results runs [--json-out F]
```

## Public data files (`tracks/a_from_scratch/public/`)

| File | Contents |
| --- | --- |
| `fen_examples.jsonl` | 10 tagged FENs (castling, en passant, promotion, endgames) used by the gate's bestmove check |
| `perft_examples.jsonl` | 10 position/depth/node rows (startpos, Kiwipete, CPW positions) used by the perft check |
| `gate_config.yaml` | public gate tunables (read by the gate runner) |
| `openings_public.pgn` | short public opening lines; informational only — the v0.1 runner starts all games from the initial position |

Agents may read all of these; nothing about the evaluation is hidden in v0.1.
