# Track A opponent pool

The benchmark owns a pool of six UCI opponents that Track A candidates are
scored against. They are implemented in `bench/ceb/match/opponents.py` (this
directory holds documentation only) and are **public by design in v0.1**:
agents may read the source and play against them as often as they like —
gate attempts and quick rounds are free; only official rounds consume budget.

Run any opponent as a standalone UCI engine:

```bash
python -m ceb.match.opponents BenchRandom
```

The internal match runner launches them the same way, argv-only (no shell),
via `opponent_command(name)`.

## The pool

| Name | Nominal rating | Strategy |
|---|---|---|
| `BenchRandom` | 400 | Uniformly random legal move. |
| `BenchGreedyCapture` | 600 | Takes the highest-valued capture available (en passant included); otherwise a random legal move. |
| `BenchMaterial1` | 800 | Depth-1 negamax, material-only evaluation. |
| `BenchPST1` | 1000 | Depth-1 negamax, material plus a center-weighted piece-square bonus and a pawn-advance bonus. |
| `BenchMiniMax2` | 1200 | Depth-2 negamax with alpha-beta pruning, material-only evaluation. |
| `BenchAlphaBeta3` | 1400 | Depth-3 alpha-beta with the material + piece-square evaluation. |

All opponents share one UCI shell and differ only in move selection. The
depth-based ones use iterative deepening up to their depth cap with a
deadline at roughly 80% of the `go movetime` budget, falling back to the
deepest completed iteration; ties among equally scored root moves are broken
randomly.

Ratings are **nominal** anchors, not measured Elo. They live in
`../scoring.yaml` (`opponent_ratings`) and mirror
`DEFAULT_OPPONENT_RATINGS` in `bench/ceb/scoring/track_a.py`. Track A
performance per opponent is `opponent_rating + delta_elo(score_rate)`, and
the ladder score is the mean across opponents.

## Determinism

Each opponent process starts from a fixed default seed and accepts

```
setoption name Seed value N
```

after which its move choices are fully deterministic for a given position
sequence. The internal match runner (`bench/ceb/match/internal_runner.py`)
sets a fresh seed per game (rounds use `base_seed = 1000 * round_number`),
so rounds are reproducible.

## UCI surface

The shell understands: `uci`, `isready`, `ucinewgame`,
`setoption name Seed value N`, `position startpos|fen ... [moves ...]`,
`go movetime N` (default 1000 ms), `go perft D` (replies
`info string perft <nodes>`), and `quit`. With no legal moves it answers
`bestmove 0000`.

## Where they are used

- Gate mini-match: 2 games vs `BenchRandom` (`../public/gate_config.yaml`).
- Quick rounds: `BenchRandom` + `BenchMaterial1`, 2 games each at 50 ms.
- Official rounds: all six opponents, 4 games each at 200 ms.

Round defaults live in `bench/ceb/rounds/round_runner.py` and can be
overridden under `round_modes` in `../scoring.yaml`. Hidden opponents are a
planned hosted-deployment feature and would mount under `../private/`; v0.1
ships none.
