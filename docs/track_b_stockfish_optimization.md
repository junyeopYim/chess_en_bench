# Track B — Stockfish search optimization

Track B measures how much playing strength an agent can add to a pinned
Stockfish baseline by editing **only search-related files**. The candidate is
scored by delta Elo versus the unmodified baseline. The agent never touches
evaluation, NNUE networks, move generation, protocol, or build files.

## Pinned baseline

The baseline is **Stockfish 18** (tag `sf_18`, commit `cb3d4ee`), pinned in
`tracks/b_stockfish_opt/stockfish.lock`:

- repo: `https://github.com/official-stockfish/Stockfish.git`
- location: `third_party/stockfish` (gitignored — never committed here)

Official evaluation must use this exact commit, never a moving branch. The
status command and the setup script both verify HEAD against the lock.

Stockfish is GPLv3 and is **not** distributed with this repository; see
`NOTICE`. Any redistribution of Stockfish sources or derived binaries must
comply with GPLv3.

## Setup

```bash
bash scripts/setup_stockfish.sh        # clone + checkout sf_18, verify cb3d4ee
ceb track-b status                     # confirm the checkout
cd third_party/stockfish/src && make -j build   # needs make + a C++17 compiler
```

The script refuses to continue if HEAD does not match the pinned commit.
After setup, `ceb track-b status` reports the HEAD commit, whether it matches
the lock, and a ready/next-step action line (schema `ceb.track_b.status/v1`
internally).

## Diff whitelist policy

Three files in `tracks/b_stockfish_opt/` define what a candidate may change:

- `allowed_paths.txt` — the only files that may differ from the baseline
  (fnmatch globs, paths relative to the Stockfish source root):
  `src/search.cpp`, `src/search.h`, `src/movepick.cpp`, `src/movepick.h`,
  `src/history.h`, `src/timeman.cpp`, `src/timeman.h`, `src/tt.cpp`,
  `src/tt.h`.
- `forbidden_paths.txt` — hard-forbidden even if a future whitelist edit
  overlapped: `src/evaluate.*`, `src/nnue/*`, `**/*.nnue`, `src/position.*`,
  `src/movegen.*`, `src/bitboard.*`, `src/uci.*`, `src/ucioption.cpp`,
  Makefiles, `scripts/*`.
- `patch_policy.yaml` — policy summary: forbidden takes precedence over
  allowed; no added or removed files; at most the 9 whitelisted files change;
  the candidate must still build with the **unmodified** Makefile and pass
  the baseline's `bench` command.

The checker (`bench/ceb/track_b/diff_policy.py`) compares the two trees by
SHA-256 content hash (skipping `.git` and similar), classifies every
added/removed/modified file, and fails on any change that matches a forbidden
pattern or is not covered by the whitelist. The standalone command is
`ceb track-b check-diff --baseline <dir> --candidate <dir>` (exit 0 on pass,
2 on violations; report schema `ceb.track_b.diff_check/v1`; `--allowed` /
`--forbidden` override the pattern files, mainly for tests).

## Automated rounds: `ceb track-b round run`

A round plays the candidate build against the baseline build and writes a
scored report:

```bash
ceb track-b round run \
  --candidate-engine /path/to/candidate/src/stockfish \
  --baseline-engine third_party/stockfish/src/stockfish \
  --baseline-src third_party/stockfish \
  --candidate-src /path/to/candidate
```

Flags: `--round N` (default 1), `--run-id ID` (default `track_b_local`),
`--games N` (default 8), `--movetime MS` (default 100), `--max-plies N`
(default 300), `--openings-limit N`, `--eval-pack DIR`, `--runs-dir DIR`.
An engine spec is either an executable path or a benchmark opponent name
(`BenchRandom` … `BenchAlphaBeta3`) — the names exist for testing only.

The runner (`bench/ceb/track_b/round_runner.py`) executes strictly in order:

1. **Diff whitelist check** — runs when `--baseline-src`/`--candidate-src`
   are given (both required together). Any violation aborts the round
   **before a single game is played** (exit 2; the diff report is attached).
2. **UCI handshake verification** for both engines; a failed handshake also
   aborts before play.
3. **Paired-opening, alternating-color games**: openings are cycled in pairs
   so the candidate plays each opening once as white and once as black
   (`ceil(games/2)` pairs). `Threads=1` and `Hash=16` are sent to **both**
   engines.
4. **Scoring** via `compute_delta_elo_report`, then artifacts under
   `runs/<run-id>/track_b_round_<n>/`: `report.json`
   (`ceb.track_b.round.report/v1` — engine ids, UCI options, `openings_used`
   ids, `eval_pack`, `diff_check`, totals, faults, score), full `match.json`
   and `games.txt` for the operator, and a sanitized `feedback.json`
   (`ceb.track_b.feedback/v1` — aggregates only: W/D/L, faults, delta Elo
   with CI, penalties, and an openings *count*; no moves or game logs).

Openings come from a mounted private eval pack when present (`--eval-pack`
or, since rounds count as official evaluation, `CEB_PRIVATE_EVAL_DIR`);
otherwise from `tracks/b_stockfish_opt/public/quick_openings.jsonl`
(4 validated openings; the `.pgn` file is kept for human readers only);
otherwise from the Track A public suite.

**Fixed conditions for real evaluations:** both engines must be builds of the
pinned Stockfish 18 (`sf_18` / `cb3d4ee`) with identical compiler flags,
`Threads=1`, fixed `Hash`, and no Syzygy tablebases. The runner enforces the
UCI options; the build provenance is documented policy, **not** enforced by
code — the runner plays whatever executables it is given.

## Delta-Elo scoring model

W/D/L feeds `ceb.scoring.track_b` (schema `ceb.score.track_b/v1`), built on
`ceb.scoring.elo`:

- `score_rate = (W + 0.5*D) / games`, clamped into (0,1) by
  `eps = 1 / (2*(games+1))`
- `delta_elo = -400 * log10(1/score_rate - 1)`
- 95% CI via a normal approximation on the per-game score (z = 1.96)
- penalties per candidate fault: illegal_move 30, timeout 15, crash 25
  Elo points; `final_delta_elo = delta_elo - penalty_points`

Per `tracks/b_stockfish_opt/track.yaml`, a run has 3 official rounds.
`tracks/b_stockfish_opt/public/quick_eval_config.yaml` documents reference
quick-eval parameters; the CLI defaults above are the operative ones.

## Implemented vs planned

Implemented:

- `stockfish.lock` pin + `scripts/setup_stockfish.sh` with commit verification
- `ceb track-b status`, `ceb track-b check-diff`
- `ceb track-b round run` — automated candidate-vs-baseline rounds with the
  abort-before-games diff check, handshake verification, paired openings,
  fixed UCI options, delta-Elo scoring, and sanitized feedback
- hidden opening packs via the shared eval-pack loader (`--eval-pack` /
  `CEB_PRIVATE_EVAL_DIR`); no hidden data is shipped in this repository

Planned / operator responsibility:

- building the pinned baseline and a flag-identical candidate build is a
  manual operator step, not automated by the runner
- fastchess/cutechess adapters
- an aggregated Track B leaderboard (the leaderboard command serves Track A;
  Track B round reports are per-run artifacts only)
