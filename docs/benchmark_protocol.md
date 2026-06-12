# Benchmark Protocol (Track A run lifecycle)

This is the full lifecycle of a Track A run, from workspace creation to the
leaderboard. Source of truth: `bench/ceb/rounds/state.py` (budget and state),
`bench/ceb/rounds/round_runner.py` (round execution),
`bench/ceb/gate/gate_runner.py` (gate), `bench/ceb/scoring/track_a.py`
(scoring and leaderboard).

## 1. Prepare a workspace

```bash
ceb workspace prepare --track A --run-id demo [--runs-dir DIR]
```

Creates `runs/demo/workspace/`, copies the track prompt to
`runs/demo/instructions.md`, writes a workspace README, and initializes
`runs/demo/state.json` (schema `ceb.run.state/v1`) with `budget_total` taken
from `tracks/a_from_scratch/track.yaml` (`official_rounds: 3`). The agent
puts its submission in the workspace: an executable `engine`, or a `build.sh`
that produces one.

## 2. Iterate against the public gate (unlimited, free)

```bash
ceb gate run --track A --workspace runs/demo/workspace [--json-out F] [--no-match]
```

Gate attempts are unlimited and never consume round budget. Checks run in
order; a hard failure skips the remaining heavy checks:

1. `format` — workspace has `engine` or `build.sh`
2. `build` — run `build.sh` if present (120 s limit)
3. `engine` — executable `./engine` exists after build
4. `handshake` — `uci`/`uciok`, `isready`/`readyok`
5. `position` — `position startpos` / `position fen` / moves accepted
6. `bestmove` — legal bestmove on public FENs, validated by the internal oracle
7. `perft` — `go perft` extension vs oracle counts (RECOMMENDED: missing
   support is a warning; wrong counts are a failure)
8. `time` — bestmove returned within the `go movetime` budget
9. `mini_match` — 2 games vs BenchRandom with zero candidate faults
   (skipped with `--no-match`)

Exit code 0 = passed, 2 = failed. The JSON report (`ceb.gate.report/v1`) is
written to `--json-out`, or to `runs/_gate/<workspace>-<timestamp>.json` by
default. A standalone `ceb gate run` does not touch `state.json`; the gate
result is recorded into the run state whenever a round runs (see below).

## 3. Spend the official round budget

```bash
ceb round run --track A --workspace runs/demo/workspace --round 1 [--quick] \
    [--run-id X] [--runs-dir DIR]
```

If `--run-id` is omitted it defaults to the workspace directory name. Every
round begins by **re-running the gate** so the round always starts from a
verified engine; the result is saved to `runs/<run_id>/gate_report.json` and
recorded in `state.json` (`gate.attempts`, `gate.passed`). If the gate fails,
the round aborts and no budget is touched.

Budget rules (`RunState.can_start_round` / `record_round`):

- **Quick rounds are free** and may be run any number of times. Quick mode
  plays BenchRandom and BenchMaterial1, 2 games each, 50 ms movetime,
  120 max plies (see `round_modes` in `tracks/a_from_scratch/scoring.yaml`).
- **Official rounds consume the budget** (3 per run). The remaining-budget
  precondition is checked before any game is played; the consumed unit is
  recorded in `state.json` together with the round result when the report is
  written. Official mode plays all six opponents — BenchRandom,
  BenchGreedyCapture, BenchMaterial1, BenchPST1, BenchMiniMax2,
  BenchAlphaBeta3 — 4 games each, 200 ms movetime, 200 max plies.

Matches run on the internal runner (`bench/ceb/match/internal_runner.py`):
every move is oracle-validated, colors alternate, each game is seeded
deterministically (`base_seed = 1000 * round_number`), and games are
adjudicated as draws at the max-ply or fifty-move limit. Illegal moves,
timeouts, and crashes lose the game for the offending side and are tallied
for penalties (illegal_move 30, timeout 15, crash 25 points each).

## 4. Per-round artifacts under runs/<run_id>/

```
runs/<run_id>/
  state.json                      # ceb.run.state/v1: budget, gate, round trajectory
  gate_report.json                # ceb.gate.report/v1 from the latest round's gate
  instructions.md                 # copy of the track prompt
  workspace/                      # the submission (if prepared via ceb workspace)
  round_N/
    report.json                   # ceb.round.report/v1: matches + score
    feedback.json                 # ceb.round.feedback/v1: sanitized aggregates
    match_vs_<Opponent>.json      # full internal-runner match report
    games_vs_<Opponent>.txt       # PGN-like UCI-movetext game records
```

`report.json` embeds the round score (`ceb.score.track_a/v1`): per-opponent
performance = `opponent_rating + delta_elo(clamped score rate)`, ladder score
= mean performance across opponents, final score = ladder score minus penalty
points. The agent-facing `feedback.json` contains only per-opponent W/D/L and
score rates, fault counts, penalty points, the scores, and generic advice —
never move logs or evaluation internals.

## 5. Final score and leaderboard

```bash
ceb leaderboard compute --track A --results runs [--json-out F]
```

The final score of a run is its **best round with a recorded score**
(`final_score_policy: best_valid_round` in `track.yaml`). Note: in v0.1 the
leaderboard (`compute_leaderboard`) considers every scored round, quick or
official; the best round's mode is shown in each entry so quick-mode bests are
visible. Output (`ceb.leaderboard/v1`) lists one entry per
`runs/*/state.json` of the requested track — run id, workspace, gate status,
rounds played, best round, and score — sorted best score first; runs with no
scored rounds sort last.

`ceb server start --host 127.0.0.1 --port 8000` serves a read-only dashboard
over the same run artifacts (requires the `server` extras).

## Track B in v0.1

Track B has no round runner yet. The implemented protocol is: pin the
baseline (`scripts/setup_stockfish.sh`, verified by `ceb track-b status`),
edit only whitelisted search files, validate the patch with
`ceb track-b check-diff --baseline <dir> --candidate <dir>`, run
candidate-vs-baseline matches yourself, and score the W/D/L with the
delta-Elo module (`bench/ceb/scoring/track_b.py`, schema
`ceb.score.track_b/v1`). Automated match orchestration for Track B is
planned, not implemented.
