# Track B — private evaluation data (mount point)

**No hidden data ships in this repository.** This directory is intentionally
empty apart from this README and exists to keep the conventional mount point
in git. No code reads this path directly; hidden data is consumed only when
an operator points the eval-pack loader at a directory.

## How hidden Track B data is loaded

Track B hidden openings resolve through the same eval-pack loader as Track A
(`bench/ceb/eval_pack.py`). An operator either passes
`ceb track-b round run ... --eval-pack <dir>` or sets
`CEB_PRIVATE_EVAL_DIR=<dir>` (Track B rounds count as official evaluation,
so the environment variable is honored). The directory contains:

- `openings_hidden.jsonl` — hidden openings, same JSONL row format as
  `tracks/a_from_scratch/public/openings_public.jsonl`:
  `{"id", "fen": "startpos"|FEN, "moves": [UCI...], "tags": [...]}`. Every
  move is oracle-validated at load time; rows without ids are assigned ids.
- `manifest.json` — optional: `{"name": ..., "openings_mode":
  "extend"|"replace"}` (default `extend`).

When a private pack is mounted, its opening list takes precedence over the
Track B public quick suite (`../public/quick_openings.jsonl`). In `extend`
mode the hidden openings are appended to the Track A public suite; use
`"openings_mode": "replace"` to play hidden openings only. With no private
pack, rounds use the Track B quick suite.

Official match parameters (game count, movetime) are **CLI flags** of
`ceb track-b round run` (`--games`, `--movetime`), not a hidden config file;
nothing in this directory configures them. The hidden FENs/openings never
reach the agent: `feedback.json` carries aggregates only, and full detail
stays in operator artifacts (`report.json`, `match.json`, `games.txt`).

`examples/eval_packs/tiny_private/` is a fake demo pack showing the exact
shape (used by tests).

## Interface any hidden evaluation must follow

- Baseline is the exact pinned ref from `../stockfish.lock` (Stockfish 18,
  tag `sf_18`, commit `cb3d4ee`); building it any other way invalidates the
  comparison. Both engines must be built with identical compiler flags.
- The candidate tree must pass the diff whitelist first; `ceb track-b round
  run --baseline-src ... --candidate-src ...` runs the check itself and
  aborts before any game on a violation. Only files matching
  `../allowed_paths.txt` may differ; anything matching
  `../forbidden_paths.txt` always fails.
- Results are reported as `ceb.track_b.round.report/v1` with an embedded
  `ceb.score.track_b/v1` score: W/D/L, clamped score rate, `delta_elo` with
  `delta_elo_ci95`, fault penalties, and `final_delta_elo`.

## Status

| Piece | State |
|---|---|
| Eval-pack loader for hidden openings (`--eval-pack` / `CEB_PRIVATE_EVAL_DIR`) | Implemented |
| Automated candidate-vs-baseline rounds (`ceb track-b round run`) | Implemented |
| Hidden opening pack contents | Operator-provided; none shipped |
| This directory read directly by code | No — conventional mount point only |
