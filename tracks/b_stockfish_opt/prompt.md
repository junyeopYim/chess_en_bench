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
- Reference local match parameters:
  `tracks/b_stockfish_opt/public/quick_eval_config.yaml`
  (20 games, 100 ms/move, alternating colors, openings in
  `public/quick_openings.pgn`).

## Task

1. Copy the baseline tree to a candidate directory (do not edit
   `third_party/stockfish` in place; the evaluator diffs candidate against
   that baseline).
2. Modify only whitelisted search files to gain playing strength.
3. Verify the candidate builds and runs, and that the diff check passes,
   before submitting.

## Inputs

- `third_party/stockfish/` — pinned baseline sources (GPLv3; see `NOTICE`)
- `tracks/b_stockfish_opt/allowed_paths.txt` — the only editable files
- `tracks/b_stockfish_opt/forbidden_paths.txt` — hard-forbidden paths
- `tracks/b_stockfish_opt/patch_policy.yaml` — policy summary
- `tracks/b_stockfish_opt/public/` — quick evaluation config and openings

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
- Run the whitelist check before every submission and only submit when it
  exits 0:

  ```bash
  ceb track-b check-diff \
    --baseline third_party/stockfish \
    --candidate <candidate-dir>
  ```

## Output format

Submit:

1. The candidate directory: a complete Stockfish source tree that differs
   from the baseline only in whitelisted files and passes
   `ceb track-b check-diff` (exit code 0).
2. A short summary (plain text or Markdown) listing each changed file, what
   was changed, and why you expect it to gain Elo.

Note: in v0.1 there is no automated candidate-vs-baseline match
orchestration. Self-test locally by playing games between your candidate
build and the baseline build (manually or with an external runner) using the
quick-eval parameters, then estimate strength with
`ceb.scoring.track_b.compute_delta_elo_report`.
