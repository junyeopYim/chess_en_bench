# Handoff

## Goal
chess_en_bench v0.1: local benchmark platform for LLM agents building (Track A)
or optimizing (Track B) chess engines.

## Current state
- Package `ceb` (under `bench/`) installs with `pip install -e ".[dev,server]"`;
  CLI `ceb` / `python -m ceb.cli` works.
- Implemented and verified: chess oracle (canonical perft counts), UCI client,
  public gate (9 checks), 6 benchmark opponents, internal match runner,
  Elo/ladder/delta-Elo scoring, round state + budget logic, leaderboard,
  FastAPI server + warm-minimal dashboard, Track B pin/whitelist tooling.
- `pytest -q`: 69 tests green. Acceptance commands (doctor, gate run,
  round run --quick, server start, api import) all pass locally.
- Examples: `examples/submissions/minimal_uci_engine_python` passes the gate;
  broken engines (illegal/timeout) fail it as intended.

## Blockers
- None for v0.1 scope.

## Next steps
- Track B: wire automated candidate-vs-baseline match orchestration
  (build pinned Stockfish, play matches, feed `ceb.scoring.track_b`).
- Optional fastchess/cutechess adapters for faster official rounds.
- Container sandboxing for untrusted submissions (docs/security.md has the plan).
- Hidden evaluation packs: populate `tracks/*/private/` per their READMEs.
