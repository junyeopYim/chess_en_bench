# Handoff

## Goal
chess_en_bench v0.2: credible local/hosted benchmark for LLM agents building
(Track A) or optimizing (Track B) chess engines.

## Current state (branch v0.2-upgrade-agent)
- v0.2 on top of the v0.1 MVP. All P0 tasks implemented and tested:
  official leaderboard excludes quick rounds (`--include-quick` diagnostic),
  run-id inference for `runs/<id>/workspace` layouts, strict gate
  (perft mandatory, used by official rounds), opening suites
  (`openings_public.jsonl`, rotated across opponents, paired colors),
  Docker sandbox (`--sandbox docker`, network-none/read-only/limits/non-root),
  hidden eval pack loader (`--eval-pack` / `CEB_PRIVATE_EVAL_DIR`,
  extend/replace via manifest, id-only failure details, sanitized feedback).
- P1: Track B automated round runner (`ceb track-b round run`: diff check →
  handshake → paired games → delta Elo), GitHub Actions CI (3.10–3.12),
  optional Stockfish limited-strength anchors (config + graceful skip).
- `pytest -q`: 104 passed, 1 skipped (Docker integration, opt-in via
  CEB_DOCKER_TESTS=1; verified passing locally with the image built).
- Sandboxed gate verified end-to-end in Docker on this machine.

## Blockers
- None for v0.2 scope.

## Next steps
- Real-Stockfish Track B end-to-end recipe (build pinned sf_18 baseline +
  candidate, then `ceb track-b round run` with both binaries).
- fastchess/cutechess adapter (still optional/planned; internal runner is
  the tested default).
- Repetition-draw detection in the internal runner (max-plies adjudication
  covers it today).
- Hosted leaderboard ingestion/signing for self-reported runs.
