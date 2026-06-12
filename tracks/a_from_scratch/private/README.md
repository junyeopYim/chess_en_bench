# Track A — private evaluation data (placeholder)

**v0.1 ships no hidden data.** This directory is intentionally empty apart
from this README and exists only to keep the path in git. No code in
`bench/ceb/` reads from it today; the gate, rounds, and scoring run entirely
on the public data in `../public/` and the public opponent pool.

## Purpose

In a hosted deployment this is the mount point for hidden evaluation packs:
data the operator uses to evaluate submissions but never returns to the
agent. Round results that depend on anything mounted here must still reach
the agent only through the sanitized feedback contract
(`specs/round_feedback_contract.md`) — aggregate W/D/L, score rates, fault
counts, and scores; never positions or move logs.

## What would mount here, and the interface it must follow

Hidden packs reuse the public file formats exactly, so the harness needs no
new parsers:

- `fen_hidden.jsonl` — extra bestmove-legality FEN suites for the official
  evaluation. Same JSONL schema as `../public/fen_examples.jsonl`:
  one object per line with `id` (string), `fen` (string), `tags` (list of
  strings).
- `perft_hidden.jsonl` — extra perft positions with expected node counts.
  Same schema as `../public/perft_examples.jsonl`: `id`, `fen`, `depth`
  (int), `nodes` (int).
- `openings_hidden.pgn` — hidden opening lines for round matches. Same shape
  as `../public/openings_public.pgn`: standard PGN headers, a short move
  sequence, result `*`.
- `opponents/` — hidden opponents beyond the public pool. Each must:
  - speak UCI and be launchable argv-only (no shell), like the public pool's
    `python -m ceb.match.opponents <Name>`;
  - be deterministic given `setoption name Seed value N`, so the internal
    match runner (`bench/ceb/match/internal_runner.py`) can seed each game;
  - have a nominal rating registered in `../scoring.yaml` under
    `opponent_ratings`, since Track A performance is
    `opponent_rating + delta_elo`.

## Status

| Piece | v0.1 |
|---|---|
| Public gate, rounds, scoring, opponents | Implemented |
| This directory wired into any code path | Not implemented |
| Hidden FEN/perft/openings/opponent packs | Planned (hosted deployments) |

Until a deployment mounts real packs here, everything the benchmark uses is
public and inspectable.
