# Reproducibility

What makes a chess_en_bench run repeatable, what is persisted so you can
audit it later, and where determinism honestly ends.

## Implemented

### Per-game seeds

The internal match runner (`bench/ceb/match/internal_runner.py`) seeds every
game. `play_match(..., base_seed=N)` gives game `i` the seed `base_seed + i`,
and `play_game` sends it to **both** engines before the first move:

    setoption name Seed value <base_seed + i>

Seed assignment by context:

- Official/quick rounds (`bench/ceb/rounds/round_runner.py`) and Track B
  rounds (`bench/ceb/track_b/round_runner.py`):
  `base_seed = 1000 * round_number`. Re-running the same round number replays
  the same seeds.
- Gate mini match (`bench/ceb/gate/gate_runner.py`): the `play_match` default,
  `base_seed = 1`.

The benchmark opponents (`python -m ceb.match.opponents <Name>`) implement the
`Seed` UCI option and reset their `random.Random` from it. Candidate engines
that reject `setoption` are tolerated. Colors alternate deterministically
(candidate is White in even-indexed games); draw adjudication is rule-based
(fifty-move rule, `max_plies` cap), not judgment-based.

### Deterministic openings

Start positions come from a validated JSONL suite
(`bench/ceb/match/openings.py`); every move of every opening is oracle-checked
at load time, so a corrupt suite raises `OpeningError` instead of silently
shifting positions. Selection is pure arithmetic, no randomness:

- A round mode takes the first `openings_limit` openings of the resolved
  suite (quick 2, official 6 — `tracks/a_from_scratch/scoring.yaml`).
- Opponent `j` gets `rotate_suite(suite, pairs, j * pairs)` — a fixed
  wrapping window, so the round covers the whole suite and the same opponent
  always sees the same openings.
- Games are played in pairs: consecutive games reuse one opening with colors
  swapped, so the candidate plays each opening as both White and Black.

Match reports record the suite (`"openings"`) and each game's `opening_id`;
round reports record `"openings_used"`.

### Eval packs are part of the evaluation conditions

Official rounds and the strict gate resolve an eval pack
(`bench/ceb/eval_pack.py`): public data plus an optional private directory
(`--eval-pack`, or `CEB_PRIVATE_EVAL_DIR` for official/strict runs). The
pack's FEN, perft, and opening contents change gate outcomes and round start
positions, so **two runs are comparable only under the same pack**. Version
your private packs: give each revision a stable `manifest.json` `"name"` —
the round report's `"eval_pack"` block records the name, source, and row
counts, which is how you audit what a score was measured against.

### Pinned Track B baseline

`tracks/b_stockfish_opt/stockfish.lock` pins Stockfish 18, tag `sf_18`, commit
`cb3d4ee` — never a moving branch. `scripts/setup_stockfish.sh` checks out
that tag and fails hard on a commit mismatch. Track B rounds
(`ceb track-b round run`) check the diff whitelist before any game, then play
paired-opening alternating-color games with `Threads=1 Hash=16` sent to both
engines. Identical compiler flags and build conditions for both binaries are
required by policy for real evaluations — documented, not enforced by code.

### Persisted run metadata

Everything an evaluation produces lands under `runs/<run_id>/`:

- `state.json` (`ceb.run.state/v1`) — gate status/attempts, official-round
  budget, full round trajectory with scores.
- `gate_report.json` (`ceb.gate.report/v1`) — per-check results plus a
  `"strict"` field saying which gate policy ran.
- `round_<N>/report.json` (`ceb.round.report/v1`) — mode, `strict_gate`,
  `eval_pack`, `openings_used`, per-opponent totals, faults, score.
- `round_<N>/match_vs_<Opponent>.json` (`ceb.match.report/v1`) — every game's
  full UCI move list, opening id, result, termination reason, final FEN.
- `round_<N>/feedback.json` (`ceb.round.feedback/v1`) — sanitized aggregates
  shown to the agent (no FENs, moves, or opening ids).

Since move lists, opening ids, and seeds (derivable as `base_seed +
game_index`) are stored, any game can be replayed and re-validated with the
internal oracle (`bench/ceb/chess/`).

### Config-driven parameters

Gate and round parameters live in version-controlled files:
`tracks/a_from_scratch/public/gate_config.yaml`,
`tracks/a_from_scratch/scoring.yaml` (round modes, opening limits, opponent
and anchor ratings, penalties), and `tracks/a_from_scratch/track.yaml`
(official round budget). Identical configs plus identical seeds and pack
means identical evaluation conditions.

### CI as a cross-version check

`.github/workflows/ci.yml` runs the full pipeline — tests, doctor, public and
strict gate, a prepared-workspace quick round (asserting
`runs/ci_smoke/round_1/report.json` exists), leaderboard in both modes — on
Python 3.10/3.11/3.12 for every push and PR, so the evaluation pipeline is
continuously checked across supported interpreters. CI uses no Stockfish and
no Docker.

## Re-running an identical quick round

Quick rounds are free (they never consume official budget), so you can repeat
one to check stability:

    ceb workspace prepare --track A --run-id demo
    # put your engine in runs/demo/workspace, then:
    ceb round run --track A --workspace runs/demo/workspace --round 1 --quick
    cp runs/demo/round_1/match_vs_BenchRandom.json /tmp/first.json
    ceb round run --track A --workspace runs/demo/workspace --round 1 --quick
    diff /tmp/first.json runs/demo/round_1/match_vs_BenchRandom.json

The run id `demo` is inferred from the `runs/demo/workspace` layout
(`default_run_id`); `--run-id` overrides. Same round number means same
`base_seed` (1000), same opponents, same openings, same movetime. Re-running
a round number **overwrites** `round_<N>/` artifacts and appends to
`state.json` — copy reports first. Expect identical move lists only within
the caveats below (`elapsed_s` always differs).

## Honest caveats

- **Movetime timing is wall-clock.** Any engine whose search depth depends on
  elapsed time can pick different moves under different machine load.
- **Depth-based opponents are time-bounded too.** `BenchRandom` and
  `BenchGreedyCapture` are fully deterministic given a seed; the others use
  iterative deepening against a deadline, so a loaded machine can change the
  chosen move even with the same seed. The same applies to optional anchor
  engines (Stockfish at `UCI_Elo` levels) when enabled.
- **Candidate engines may be nondeterministic.** Nothing forces a submission
  to honor `Seed`; threads, hash tables, or own timing logic can vary runs.
- **Timeout and fault boundaries are timing-sensitive** near
  `movetime + grace_ms`.
- **Environment pinning is partial.** `--sandbox docker` runs evaluations in
  the `chess-en-bench-evaluator:0.2` image (`python:3.12-slim` base), which
  fixes the Python runtime — but the base tag is not digest-pinned, so
  rebuilds on different days can differ, and host execution (the default)
  uses whatever the machine has.

## Planned (not implemented)

A fastchess/cutechess adapter for external match orchestration. All match
play today goes through the internal runner described above.
