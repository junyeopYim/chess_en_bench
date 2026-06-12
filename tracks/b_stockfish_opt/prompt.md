# Track B agent prompt — Stockfish search optimization

This is the prompt template handed to an LLM coding agent for a Track B run.

## Role

You are an expert chess-engine developer. Your job is to make a pinned
Stockfish baseline play stronger chess by improving **only its search
behavior** — search, move ordering, history heuristics, time management, and
the transposition table.

## Context

- Baseline: Stockfish 18, tag `sf_18`, commit `cb3d4ee`, pinned in
  `tracks/b_stockfish_opt/stockfish.lock`. Sources are at
  `third_party/stockfish` (fetch with `bash scripts/setup_stockfish.sh`;
  verify with `ceb track-b status`).
- You are scored by delta Elo of your candidate versus the unmodified
  baseline, with a 95% confidence interval. Faults cost Elo points per
  occurrence: illegal move 30, timeout 15, crash 25. A run has 3 official
  rounds; the best valid result counts.
- Evaluation games are played by `ceb track-b round run`: paired openings
  (each opening played as white and black), `Threads=1` `Hash=16` sent to
  both engines, 100 ms per move by default. The public quick suite is
  `tracks/b_stockfish_opt/public/quick_openings.jsonl`; official rounds may
  use hidden openings, so do not tune to specific lines.

## Task

1. Copy the baseline tree to a candidate directory (do not edit
   `third_party/stockfish` in place; the evaluator diffs candidate against
   that baseline).
2. Modify only whitelisted search files to gain playing strength.
3. Build both engines and self-score locally (see the loop below), iterating
   until the diff check passes and delta Elo improves.

## Inputs

- `third_party/stockfish/` — pinned baseline sources (GPLv3; see `NOTICE`)
- `tracks/b_stockfish_opt/allowed_paths.txt` — the only editable files
- `tracks/b_stockfish_opt/forbidden_paths.txt` — hard-forbidden paths
- `tracks/b_stockfish_opt/patch_policy.yaml` — policy summary
- `tracks/b_stockfish_opt/public/` — quick openings and reference parameters

## Constraints (violations invalidate the submission)

- Edit **only** these 9 files (relative to the Stockfish source root):
  `src/search.cpp`, `src/search.h`, `src/movepick.cpp`, `src/movepick.h`,
  `src/history.h`, `src/timeman.cpp`, `src/timeman.h`, `src/tt.cpp`,
  `src/tt.h`.
- Never touch evaluation (`src/evaluate.*`), NNUE code or networks
  (`src/nnue/*`, `*.nnue`), board/move generation (`src/position.*`,
  `src/movegen.*`, `src/bitboard.*`), UCI protocol (`src/uci.*`,
  `src/ucioption.cpp`), any Makefile, or `scripts/`. Forbidden beats allowed.
- Do not add or remove files. Modify whitelisted files only.
- The candidate must build with the **unmodified** Makefile:
  `cd <candidate>/src && make -j build` must succeed, and
  `./stockfish bench` must run to completion.
- The candidate must remain a correct UCI engine: no illegal moves, no
  crashes, and it must respect time controls (timeouts are penalized).

## Self-scoring loop

Before every submission, run a local round; it performs the diff whitelist
check first (a violation aborts before any game), verifies both UCI
handshakes, plays the match, and writes a delta-Elo report:

```bash
ceb track-b round run \
  --candidate-engine <candidate-dir>/src/stockfish \
  --baseline-engine third_party/stockfish/src/stockfish \
  --baseline-src third_party/stockfish \
  --candidate-src <candidate-dir>
```

Read `runs/track_b_local/track_b_round_1/feedback.json` for your aggregate
result (`final_delta_elo`, CI, faults). Increase `--games` for a tighter
CI. Only submit when the command exits 0 with zero faults.

## Output format

Submit:

1. The candidate directory: a complete Stockfish source tree that differs
   from the baseline only in whitelisted files and passes the diff check
   (`ceb track-b check-diff` exit code 0).
2. A short summary (plain text or Markdown) listing each changed file, what
   was changed, and why you expect it to gain Elo.
