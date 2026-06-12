# Benchmark Protocol (Track A run lifecycle)

This is the full lifecycle of a Track A run, from workspace creation to the
leaderboard. Source of truth: `bench/ceb/rounds/state.py` (budget and state),
`bench/ceb/rounds/round_runner.py` (round execution),
`bench/ceb/gate/gate_runner.py` (gate), `bench/ceb/eval_pack.py` (data packs),
`bench/ceb/scoring/track_a.py` (scoring and leaderboard).

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
ceb gate run --track A --workspace runs/demo/workspace \
    [--strict] [--sandbox docker] [--json-out F] [--no-match]
```

Gate attempts are unlimited and never consume round budget. Checks run in
order; a hard failure skips the remaining heavy checks:

1. `format` — workspace has `engine` or `build.sh`
2. `build` — run `build.sh` if present (120 s limit)
3. `engine` — executable `./engine` exists after build
4. `handshake` — `uci`/`uciok`, `isready`/`readyok`
5. `position` — `position startpos` / `position fen` / moves accepted
6. `bestmove` — legal bestmove on the pack's FENs, validated by the oracle
7. `perft` — `go perft` extension vs oracle counts. Default mode: missing
   support is a warning, wrong counts fail. **Strict mode (`--strict`)**:
   perft is MANDATORY and a hard check — missing support or wrong counts
   fail the gate and skip the remaining checks.
8. `time` — bestmove returned within the `go movetime` budget
9. `mini_match` — 2 games vs BenchRandom with zero candidate faults
   (skipped with `--no-match`)

Exit code 0 = passed, 2 = failed. The JSON report (`ceb.gate.report/v1`,
with a `strict` field) is written to `--json-out`, or to
`runs/_gate/<workspace>-<timestamp>.json` by default. Bestmove/perft failure
details quote row ids only, never FENs, so hidden positions cannot leak.
A standalone `ceb gate run` defaults to non-strict and does not touch
`state.json`; the gate result is recorded into the run state whenever a
round runs (see below). `--sandbox docker` re-runs the gate inside the
evaluator image (recommended for untrusted submissions, see step 6).

## 3. Spend the official round budget

```bash
ceb round run --track A --workspace runs/demo/workspace --round 1 [--quick] \
    [--run-id X] [--runs-dir DIR] [--sandbox docker] [--eval-pack DIR]
```

If `--run-id` is omitted it is inferred from the workspace path
(`default_run_id`): a directory named `workspace` whose parent holds a
`state.json` uses the parent name (`runs/demo/workspace` → `demo`);
otherwise the workspace directory name is used. `--run-id` always overrides.

Every round begins by **re-running the gate**. Official rounds always run
the **strict** gate (`go perft` mandatory); quick rounds run the non-strict
gate. The result is saved to `runs/<run_id>/gate_report.json` and recorded
in `state.json` (`gate.attempts`, `gate.passed`). If the gate fails, the
round aborts and no budget is touched.

The round's data comes from a resolved **eval pack**
(`bench/ceb/eval_pack.py`): public FENs, perft expectations, and the opening
suite (`tracks/a_from_scratch/public/`), optionally extended by an
operator-mounted private pack. An explicit `--eval-pack DIR` applies to any
gate or round; the `CEB_PRIVATE_EVAL_DIR` environment variable applies ONLY
to official rounds and strict gates. No hidden data ships in this repo
(`examples/eval_packs/tiny_private/` documents the shape).

Budget rules (`RunState.can_start_round` / `record_round`):

- **Quick rounds are free** and may be run any number of times. Quick mode
  plays BenchRandom and BenchMaterial1, 2 games each, 50 ms movetime,
  120 max plies, first 2 openings of the suite (see `round_modes` in
  `tracks/a_from_scratch/scoring.yaml`).
- **Official rounds consume the budget** (3 per run). The remaining-budget
  precondition is checked before any game is played; the consumed unit is
  recorded in `state.json` together with the round result. Official mode
  plays all six opponents — BenchRandom, BenchGreedyCapture, BenchMaterial1,
  BenchPST1, BenchMiniMax2, BenchAlphaBeta3 — 4 games each, 200 ms movetime,
  200 max plies, first 6 openings of the suite.

Games start from the opening suite (canonical JSONL, every move
oracle-validated; `bench/ceb/match/openings.py`). Consecutive game pairs use
the same opening with colors swapped, so the candidate plays each opening as
both white and black; the suite is rotated across opponents (`rotate_suite`,
offset `j * pairs`) so the round covers more openings than any single match.
Matches run on the internal runner (`bench/ceb/match/internal_runner.py`):
every move is oracle-validated, each game is seeded deterministically
(`base_seed = 1000 * round_number`), and games are adjudicated as draws at
the max-ply or fifty-move limit. Illegal moves, timeouts, and crashes lose
the game for the offending side and are tallied for penalties (illegal_move
30, timeout 15, crash 25). Optional limited-strength **anchor opponents**
(Stockfish `UCI_Elo` levels, `anchor_opponents` in `scoring.yaml`) can be
added to a mode's `anchors` list; a missing engine binary skips the anchor
with a progress note, never a failure.

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

`report.json` records `mode`, `strict_gate`, `eval_pack` (name, source, row
counts), and `openings_used` (all opening ids played), and embeds the round
score (`ceb.score.track_a/v1`): per-opponent performance =
`opponent_rating + delta_elo(clamped score rate)`, ladder score = mean
performance, final score = ladder score minus penalty points. Match reports
list their `openings` and tag each game with its `opening_id`. The
agent-facing `feedback.json` contains aggregates only — per-opponent W/D/L
and score rates, fault counts, penalty points, the scores, and generic
advice. No FENs, no moves, no opening ids; full detail stays in the
operator artifacts (`report.json`, `match_vs_*.json`).

## 5. Final score and leaderboard

```bash
ceb leaderboard compute --track A --results runs [--json-out F] [--include-quick]
```

The official leaderboard ranks each run by its **best official round with a
recorded score**; quick rounds are excluded by default and `--include-quick`
is a clearly labelled diagnostic view. See `docs/leaderboard_policy.md`.
`ceb server start --host 127.0.0.1 --port 8000` serves a read-only dashboard
and `/api/leaderboard` over the same run artifacts (`server` extras).

## 6. Sandboxing (recommended for untrusted submissions)

`ceb gate run --sandbox docker` / `ceb round run --sandbox docker` re-invoke
`ceb` inside the `chess-en-bench-evaluator:0.2` image
(`infra/docker/evaluator.Dockerfile`, built by
`scripts/build_evaluator_image.sh`): no network, read-only rootfs with the
repo mounted read-only at `/bench`, only `runs/` and the workspace writable,
CPU/memory/pids caps, `no-new-privileges`, host uid:gid, argv-only spawning.
Missing docker or image raises an actionable error. The default remains
`--sandbox none`; `--eval-pack` is not supported together with
`--sandbox docker`.

## Track B automated rounds

```bash
ceb track-b round run --candidate-engine X --baseline-engine Y \
    [--baseline-src D --candidate-src D] [--games N --movetime MS]
```

Order: diff whitelist check (a violation aborts before any game) → UCI
handshake verification for both engines → paired-opening alternating-color
games with `Threads=1 Hash=16` sent to both → delta-Elo scoring →
`report.json` (`ceb.track_b.round.report/v1`) plus sanitized `feedback.json`
(`ceb.track_b.feedback/v1`, aggregates only). An engine spec is an
executable path or a benchmark opponent name (for testing). Openings: the
private pack if mounted, else `tracks/b_stockfish_opt/public/quick_openings.jsonl`,
else the Track A public suite. For real evaluations both engines must be
builds of the pinned Stockfish 18 (`sf_18` / `cb3d4ee`) with identical
compiler flags, `Threads=1`, fixed Hash, no Syzygy — documented policy, not
enforced by code. A fastchess/cutechess adapter is planned, not implemented.
