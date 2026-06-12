# Track B — private evaluation data (placeholder)

**v0.1 ships no hidden data.** This directory is intentionally empty apart
from this README and exists only to keep the path in git. No code in
`bench/ceb/` reads from it today.

Track B in v0.1 implements: the pinned baseline lock (`../stockfish.lock`,
Stockfish 18, tag `sf_18`, commit `cb3d4ee` — never a moving branch), the
allowed/forbidden path lists, the diff whitelist checker
(`ceb track-b check-diff`), the status command (`ceb track-b status`),
`scripts/setup_stockfish.sh`, and the delta-Elo scoring module
(`bench/ceb/scoring/track_b.py`, schema `ceb.score.track_b/v1`). Automated
candidate-vs-baseline match orchestration is **not** implemented in v0.1;
`../public/quick_eval_config.yaml` describes the local quick evaluation
parameters an operator would run by hand.

## Purpose

In a hosted deployment this is the mount point for the hidden official
evaluation pack — the data that keeps candidates from overfitting the
match conditions:

- `eval_config.yaml` — the official evaluation parameters. Same keys as
  `../public/quick_eval_config.yaml` (`games`, `movetime_ms`, `max_plies`,
  `openings`, `alternating_colors`, `score_model`, `confidence`), with a much
  larger game count so the 95% CI on delta Elo is meaningful.
- `openings_hidden.pgn` — the hidden opening book for official
  candidate-vs-baseline games. Same shape as `../public/quick_openings.pgn`:
  standard PGN headers, a short line, result `*`.

## Interface any hidden evaluation must follow

- Baseline is the exact pinned ref from `../stockfish.lock`; building it any
  other way invalidates the comparison.
- The candidate tree must pass the diff whitelist first:

  ```bash
  ceb track-b check-diff --baseline third_party/stockfish --candidate <dir>
  ```

  Only files matching `../allowed_paths.txt` may differ; anything matching
  `../forbidden_paths.txt` always fails.
- Results are reported as `ceb.score.track_b/v1`: candidate-vs-baseline
  W/D/L, clamped score rate, `delta_elo` with `delta_elo_ci95`, fault
  penalties, and `final_delta_elo`.

## Status

| Piece | v0.1 |
|---|---|
| Lock, path lists, diff checker, status, setup script, scoring module | Implemented |
| Automated candidate-vs-baseline orchestration | Not implemented |
| This directory wired into any code path | Not implemented |
| Hidden eval config and opening book | Planned (hosted deployments) |
