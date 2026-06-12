# Scoring

How chess_en_bench turns game results into scores. Implementation:
`bench/ceb/scoring/elo.py`, `track_a.py`, `track_b.py`. Track A constants are
configured in `tracks/a_from_scratch/scoring.yaml`.

## Core Elo math (`ceb.scoring.elo`)

All scoring starts from W/D/L counts of one pairing:

```
score_rate = (wins + 0.5 * draws) / games
eps        = 1 / (2 * (games + 1))
clamped    = min(max(score_rate, eps), 1 - eps)
delta_elo  = -400 * log10(1 / clamped - 1)
```

`delta_elo` is the Elo difference implied by the (clamped) score rate under
the standard logistic model. Positive means the candidate outperformed the
reference (the opponent in Track A, the pinned baseline in Track B). The
result is normalized so an exactly even score yields `0.0`, never `-0.0`.

### Why clamp?

A perfect 4-0 score gives `score_rate = 1.0`, and `log10(1/1 - 1)` is
undefined (infinite Elo). The clamp keeps the rate strictly inside (0, 1)
with a margin that shrinks as evidence grows: with 4 games,
`eps = 1/10 = 0.1`, so a sweep maps to 0.9 instead of 1.0; with 100 games
`eps = 1/202 ≈ 0.005`, so large samples are barely affected. This caps how
much Elo a tiny sample can claim.

### Worked examples

| W-D-L | games | raw rate | clamped | delta Elo |
|-------|-------|----------|---------|-----------|
| 3-0-1 | 4 | 0.75 | 0.75 | **+190.8** |
| 4-0-0 | 4 | 1.00 | 0.90 | +381.7 |
| 3-1-0 | 4 | 0.875 | 0.875 | +338.0 |
| 2-0-2 | 4 | 0.50 | 0.50 | 0.0 |
| 0-0-4 | 4 | 0.00 | 0.10 | -381.7 |

Check `0.75 -> +190.8` by hand: `-400 * log10(1/0.75 - 1)
= -400 * log10(1/3) = 400 * log10(3) ≈ 190.85`.

### 95% confidence interval

`delta_elo_ci(wins, draws, losses, z=1.96)` uses a normal approximation on
the mean per-game score (draws count 0.5):

```
p   = score_rate
var = (W*(1-p)^2 + D*(0.5-p)^2 + L*(0-p)^2) / games
se  = sqrt(var / games)
(lo, mid, hi) = delta_elo(clamp(p - z*se)), delta_elo(clamp(p)), delta_elo(clamp(p + z*se))
```

Example: 10W 6D 4L in 20 games gives `p = 0.65`, `se ≈ 0.0873`, so the
interval on the rate is [0.479, 0.821] and on Elo
**+107.5 with CI95 [-14.7, +264.8]**. The interval is wide because 20 games
carry little information; treat small-sample deltas accordingly.

## Penalties (both tracks)

Per candidate fault, subtracted from the final score / final delta Elo:

| Fault | Points |
|-------|--------|
| illegal_move | 30 |
| timeout | 15 |
| crash | 25 |

Fault counts come from the internal match runner's `candidate_faults`
(keys `illegal`, `timeout`, `crash`) and are summed across all games in the
round.

## Track A: ladder score (`ceb.score.track_a/v1`)

`compute_round_score(match_reports, ...)` aggregates one internal-runner
report per opponent:

- Per opponent: `performance = opponent_rating + delta_elo(clamped rate)`.
  Ratings come from `opponent_ratings` in `scoring.yaml` (nominal:
  BenchRandom 400, BenchGreedyCapture 600, BenchMaterial1 800,
  BenchPST1 1000, BenchMiniMax2 1200, BenchAlphaBeta3 1400). The round
  runner merges the `rating` values of `anchor_opponents` entries
  (SF18_UCI_Elo_1320/1600/1900/2200) into that table when not already
  present, so optional anchor matches score the same way. Unknown opponents
  default to 800.
- `ladder_score` = mean of all non-null per-opponent performances.
- `final_score = ladder_score - penalty_points`, rounded to 0.1.
- Opponents with 0 games get null rate/delta/performance and are excluded
  from the mean; if no opponent has games, `final_score` is null.

Example report (official round, 4 games per opponent, one timeout):

```json
{
  "schema": "ceb.score.track_a/v1",
  "per_opponent": [
    {"opponent": "BenchRandom", "opponent_rating": 400, "wins": 4, "draws": 0,
     "losses": 0, "games": 4, "score_rate": 0.9, "delta_elo": 381.7,
     "performance": 781.7},
    {"opponent": "BenchPST1", "opponent_rating": 1000, "wins": 2, "draws": 1,
     "losses": 1, "games": 4, "score_rate": 0.625, "delta_elo": 88.7,
     "performance": 1088.7}
  ],
  "faults": {"illegal": 0, "timeout": 1, "crash": 0},
  "penalty_points": 15,
  "ladder_score": 995.4,
  "final_score": 980.4
}
```

(`per_opponent` shortened; a real official round has all six opponents.)

### Leaderboard (`ceb.leaderboard/v1`)

`compute_leaderboard(results_dir, track, include_quick=False)` scans
`runs/*/state.json` and ranks runs by their best scored round. The official
policy counts **official rounds only**; rounds recorded without a `mode`
field count as official (legacy states). `include_quick=True`
(CLI `ceb leaderboard compute --include-quick`, API
`/api/leaderboard?include_quick=true`) is a diagnostic view that also ranks
quick rounds — the CLI labels it as non-official and it must never be
presented as an official ranking. The board JSON echoes the flag in an
`include_quick` field, and each entry carries `official_rounds_played`
alongside `rounds_played`. See `docs/leaderboard_policy.md`.

## Track B: delta Elo vs baseline (`ceb.score.track_b/v1`)

`compute_delta_elo_report(wins, draws, losses, faults=None)` scores a
candidate Stockfish build against the pinned baseline (sf_18, cb3d4ee):

```json
{
  "schema": "ceb.score.track_b/v1",
  "wins": 10, "draws": 6, "losses": 4, "games": 20,
  "faults": {"illegal": 0, "timeout": 0, "crash": 0},
  "score_rate": 0.65,
  "delta_elo": 107.5,
  "delta_elo_ci95": [-14.7, 264.8],
  "penalty_points": 0,
  "final_delta_elo": 107.5
}
```

With 0 games, `score_rate`, `delta_elo`, `delta_elo_ci95`, and
`final_delta_elo` are null. `ceb track-b round run` produces this score
automatically and embeds it in the round report
(`ceb.track_b.round.report/v1`, operator-facing, full detail) next to a
sanitized `feedback.json` (`ceb.track_b.feedback/v1`, aggregates only).
**Planned, not implemented:** a fastchess/cutechess match-runner adapter —
games currently run through the internal match runner.

## Reproducing the numbers

```bash
python -c "import sys; sys.path.insert(0,'bench'); \
from ceb.scoring import elo; print(elo.delta_elo(0.75))"        # 190.848...
python -c "import sys; sys.path.insert(0,'bench'); \
from ceb.scoring import elo; print(elo.delta_elo_ci(10, 6, 4))"  # (-14.7, 107.5, 264.8)
```
