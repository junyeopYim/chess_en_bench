# Reproducibility

What makes a chess_en_bench v0.1 run repeatable, what is persisted so you can
audit it later, and where determinism honestly ends.

## Implemented in v0.1

### Per-game seeds

The internal match runner (`bench/ceb/match/internal_runner.py`) seeds every
game. `play_match(..., base_seed=N)` gives game `i` the seed `base_seed + i`,
and `play_game` sends it to **both** engines before the first move:

    setoption name Seed value <base_seed + i>

Seed assignment by context:

- Official/quick rounds (`bench/ceb/rounds/round_runner.py`):
  `base_seed = 1000 * round_number`. Re-running the same round number replays
  the same seeds.
- Gate mini match (`bench/ceb/gate/gate_runner.py`): the `play_match` default,
  `base_seed = 1`.

The benchmark opponents (`python -m ceb.match.opponents <Name>`) implement the
`Seed` UCI option and reset their `random.Random` from it, so their move
choices are a deterministic function of seed and position. Candidate engines
that reject `setoption` are tolerated — the runner ignores the failure.

Colors alternate deterministically: the candidate is White in even-indexed
games (0-based). Draw adjudication is rule-based (fifty-move rule, `max_plies`
cap), not judgment-based.

### Pinned Track B baseline

`tracks/b_stockfish_opt/stockfish.lock` pins Stockfish 18, tag `sf_18`, commit
`cb3d4ee` — never a moving branch. `scripts/setup_stockfish.sh` checks out that
tag into `third_party/stockfish` and **fails hard** if `HEAD` does not match
the pinned commit. Every Track B diff check therefore compares against the
same baseline source.

### Persisted run metadata

Everything an evaluation produces lands under `runs/<run_id>/`:

- `state.json` (`ceb.run.state/v1`) — gate status/attempts, official-round
  budget, and the full round trajectory with scores.
- `gate_report.json` (`ceb.gate.report/v1`) — per-check results.
- `round_<N>/report.json` (`ceb.round.report/v1`) — mode, per-opponent
  totals, faults, score.
- `round_<N>/match_vs_<Opponent>.json` (`ceb.match.report/v1`) — every game's
  full UCI move list, result, termination reason, fault, and final FEN.
- `round_<N>/games_vs_<Opponent>.txt` — PGN-like games in UCI movetext.
- `round_<N>/feedback.json` (`ceb.round.feedback/v1`) — the sanitized
  aggregate feedback shown to the agent.

Since move lists and seeds (derivable as `base_seed + game_index`) are stored,
any game can be replayed and re-validated with the internal oracle
(`bench/ceb/chess/`).

### Config-driven parameters

Gate and round parameters live in version-controlled files, not code:
`tracks/a_from_scratch/public/gate_config.yaml` (timeouts, movetimes, mini
match), `tracks/a_from_scratch/scoring.yaml` (round modes, opponent ratings,
penalties), and `tracks/a_from_scratch/track.yaml` (official round budget).
Identical configs plus identical seeds means identical evaluation conditions.

## Re-running an identical quick round

Quick rounds are free (they never consume official budget), so you can repeat
one to check stability:

    ceb workspace prepare --track A --run-id demo
    # put your engine in runs/demo/workspace, then:
    ceb round run --track A --workspace runs/demo/workspace --round 1 --quick --run-id demo
    cp runs/demo/round_1/match_vs_BenchRandom.json /tmp/first.json
    ceb round run --track A --workspace runs/demo/workspace --round 1 --quick --run-id demo
    diff /tmp/first.json runs/demo/round_1/match_vs_BenchRandom.json

Same round number means same `base_seed` (1000), same opponents, same game
count, same movetime. Note that re-running a round number **overwrites** the
`round_<N>/` artifacts and appends a new entry to `state.json` — copy reports
first if you want to compare. Expect identical move lists only within the
caveats below.

## Honest caveats

- **Movetime timing is wall-clock.** Games run under `go movetime`, so any
  engine whose search depth depends on elapsed time can pick different moves
  under different machine load. This is inherent to time-based play.
- **The stronger opponents are time-bounded too.** `BenchRandom` and
  `BenchGreedyCapture` are fully deterministic given a seed. The depth-based
  opponents (`BenchMaterial1`, `BenchPST1`, `BenchMiniMax2`, `BenchAlphaBeta3`)
  use iterative deepening against a deadline (80% of movetime), so on a slow
  or loaded machine an iteration may not complete and the chosen move can
  differ even with the same seed.
- **Candidate engines may be nondeterministic.** Nothing forces a submission
  to honor the `Seed` option; engines with threads, hash tables, or their own
  timing logic can vary run to run.
- **Timeout and fault boundaries are timing-sensitive.** An engine answering
  near `movetime + grace_ms` may be a timeout fault on one run and not the
  next.
- **No environment pinning.** v0.1 runs on the host (Docker sandboxing is
  recommended in docs but not implemented), so compiler, libc, and Python
  versions are whatever the machine has.

## Planned (not in v0.1)

Automated Track B candidate-vs-baseline match orchestration. Today Track B
ships the pinned baseline, the diff whitelist checker (`ceb track-b
check-diff`), `ceb track-b status`, and the delta-Elo scoring module
(`ceb.score.track_b/v1`); reproducible Track B match replay will arrive with
the orchestration.
