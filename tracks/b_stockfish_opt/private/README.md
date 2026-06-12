# Track B — private evaluation data (mount point)

**No hidden data ships in this repository.** This directory is intentionally
empty apart from this README and exists to keep the conventional mount point
in git. No code reads this path directly; hidden data is consumed only when an
operator points the eval-pack loader at a directory.

The loader is real: Track B hidden openings resolve through the same eval-pack
loader as Track A (`bench/ceb/eval_pack.py`). The full eval-pack interface —
pack files, hidden-row id assignment, hidden-safe loading, the
combine-with-jail guarantee, and `eval_pack_hash` versioning — is documented
once in **[`docs/EVAL_PACKS.md`](../../../docs/EVAL_PACKS.md)**. The notes
below are the Track B specifics.

## How hidden Track B data is loaded

An operator either passes `ceb track-b round run ... --eval-pack <dir>` (also
accepted by `ceb track-b official run`) or sets `CEB_PRIVATE_EVAL_DIR=<dir>`.
Track B rounds count as official evaluation, so the environment variable is
always honored (`bench/ceb/track_b/round_runner.py` resolves the pack with
`allow_env=True`). Only the hidden openings matter for Track B:

- `openings_hidden.jsonl` — hidden openings, same JSONL row format as
  `tracks/a_from_scratch/public/openings_public.jsonl`:
  `{"id", "fen": "startpos"|FEN, "moves": [UCI...], "tags": [...]}`. Every move
  is oracle-validated at load time; rows without ids are assigned ids.
- `manifest.json` — optional `{"name": ..., "openings_mode":
  "extend"|"replace"}` (default `extend`).

In `extend` mode the hidden openings are appended to the public suite; use
`"openings_mode": "replace"` to play hidden openings only. With no private
pack, rounds use the Track B public quick suite
(`../public/quick_openings.jsonl`).

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
  run --baseline-src ... --candidate-src ...` runs the check itself and aborts
  before any game on a violation. Only files matching `../allowed_paths.txt`
  may differ; anything matching `../forbidden_paths.txt` always fails.
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
