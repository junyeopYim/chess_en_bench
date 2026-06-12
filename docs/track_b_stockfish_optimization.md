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

`ceb track-b status` output before setup (real example):

```
Track B baseline status
  pinned release : Stockfish 18 (tag sf_18, commit cb3d4ee)
  sources        : /path/to/chess_en_bench/third_party/stockfish (absent)
  -> Stockfish sources not found. Run: bash scripts/setup_stockfish.sh
```

After setup it reports the HEAD commit, whether it matches the lock, and a
ready/next-step action line (schema `ceb.track_b.status/v1` internally).

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
pattern or is not covered by the whitelist. Note the operative enforcement is
the pattern check itself; `max_changed_files` in `patch_policy.yaml` is
implied by the 9-entry whitelist, not a separately coded limit.

## Checking a candidate

```bash
ceb track-b check-diff \
  --baseline third_party/stockfish \
  --candidate /path/to/candidate
```

Exit code 0 on pass, 2 on violations. Example failing report
(schema `ceb.track_b.diff_check/v1`):

```json
{
  "schema": "ceb.track_b.diff_check/v1",
  "baseline": "third_party/stockfish",
  "candidate": "/path/to/candidate",
  "changed_total": 2,
  "allowed_changes": [
    {"path": "src/search.cpp", "change": "modified"}
  ],
  "violations": [
    {"path": "src/evaluate.cpp", "change": "modified",
     "reason": "matches forbidden pattern"}
  ],
  "passed": false
}
```

`--allowed` / `--forbidden` can override the pattern files (mainly for tests).

## Delta-Elo evaluation model

Candidate and baseline play a match; W/D/L feeds `ceb.scoring.track_b`
(schema `ceb.score.track_b/v1`), built on `ceb.scoring.elo`:

- `score_rate = (W + 0.5*D) / games`, clamped into (0,1) by
  `eps = 1 / (2*(games+1))`
- `delta_elo = -400 * log10(1/score_rate - 1)`
- 95% CI via a normal approximation on the per-game score (z = 1.96)
- penalties per candidate fault: illegal_move 30, timeout 15, crash 25
  Elo points; `final_delta_elo = delta_elo - penalty_points`

Reference match parameters for local quick evaluation live in
`tracks/b_stockfish_opt/public/quick_eval_config.yaml` (20 games, 100 ms per
move, max 300 plies, alternating colors, openings from
`public/quick_openings.pgn`). Per `tracks/b_stockfish_opt/track.yaml`, a run
has 3 official rounds.

To score a manually played match:

```bash
python -c "from ceb.scoring.track_b import compute_delta_elo_report as f; \
import json; print(json.dumps(f(wins=12, draws=5, losses=3), indent=2))"
```

## Implemented in v0.1 vs planned

Implemented in v0.1:

- `stockfish.lock` pin + `scripts/setup_stockfish.sh` with commit verification
- `ceb track-b status` (baseline/setup status)
- `ceb track-b check-diff` (content-hash tree diff against the whitelist)
- `allowed_paths.txt`, `forbidden_paths.txt`, `patch_policy.yaml`
- delta-Elo scoring module with CI and fault penalties
- public quick-eval reference config and openings

Planned, **not** in v0.1:

- automated candidate-vs-baseline match orchestration (`ceb round run`
  currently serves Track A only; Track B matches must be run manually or with
  an external runner such as fastchess/cutechess, then scored as above)
- hidden official evaluation configs/openings — v0.1 is a local MVP with no
  hidden data; `tracks/*/private/` exists only as a documented placeholder
- fastchess/cutechess adapters and Docker sandboxing for engine processes
