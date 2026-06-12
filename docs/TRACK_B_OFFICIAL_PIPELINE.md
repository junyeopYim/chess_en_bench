# Track B — source-first official pipeline

This is the source-build path that turns a Track B candidate *source tree*
into a scored, signed delta-Elo result. It exists alongside the executable-only
`ceb track-b round run` (which plays two engines you already built); see
`docs/track_b_stockfish_optimization.md` for the track rules, the diff
whitelist, the pinned baseline, and delta-Elo scoring.

Command: `ceb track-b official run`
(`bench/ceb/track_b/official_pipeline.py`, `run_official_track_b`).

## Command

```bash
ceb track-b official run \
  --candidate-src /path/to/candidate \
  [--baseline-src third_party/stockfish] \
  [--eval-pack DIR] \
  [--engine-jail none|docker] \
  [--build-script ceb_build.sh] \
  [--engine-relpath ceb_engine] \
  [--games 8] [--movetime 100] [--max-plies 300] \
  [--run-id track_b_official] [--runs-dir DIR]
```

- `--candidate-src` is required.
- `--baseline-src` defaults to `third_party/stockfish`. If that directory is
  absent and no `--baseline-src` is given, the pipeline aborts with a message
  pointing at `scripts/setup_stockfish.sh` and the pinned tag (`sf_18`).
- `--build-script` (default `ceb_build.sh`) and `--engine-relpath` (default
  `ceb_engine`) name the build wrapper each tree provides and the engine it
  produces. Both the baseline and the candidate are built with the **same**
  build script and engine relpath.
- `--engine-jail docker` confines only the candidate engine (see below).
- Exit 2 on any abort (scan failure, missing build script, build failure,
  failed handshake), with a sanitized one-line message.

## What runs, in order

`run_official_track_b` executes strictly in this order:

1. **Resolve the baseline tree.** `--baseline-src`, or `third_party/stockfish`
   at the pinned `sf_18` / `cb3d4ee`. (The pin lives in
   `tracks/b_stockfish_opt/stockfish.lock`; the pipeline does not re-verify
   the commit hash — that is `scripts/setup_stockfish.sh` / `ceb track-b
   status`.)
2. **Scan** the candidate against the baseline with `scan_track_b`
   (`bench/ceb/scan/track_b_scan.py`): diff whitelist plus content rules
   (binary/NNUE/book/tablebase payloads, harness fingerprinting,
   network/process syscalls in changed source, symlinks). Any `fail` finding
   or whitelist violation aborts **before anything is built**.
3. **Build the baseline**, then **build the candidate**, each by running
   `bash <build-script>` with the tree as the working directory (build
   timeout 1800 s). A non-zero exit, a missing script, or a build that does
   not produce `<engine-relpath>` aborts. The produced engine is made
   executable (`chmod +x`).
4. **Play candidate-vs-baseline paired matches** via `run_track_b_round`
   (the internal runner — the trusted reference). This reuses the Track B
   round flow: UCI handshakes, paired alternating-color openings,
   `Threads=1` / `Hash=16` to both engines, delta-Elo scoring.
5. **Assemble metadata** (`build_metadata`) and add a `track_b` block:
   `baseline_tree_hash` and `candidate_tree_hash` (sha256 over each tree's
   relative paths + contents, via `hash_directory`) and `build_script`.
6. **Sign** the result (`sign_result`) and write artifacts.

## Output

A single result dict, schema `ceb.track_b.official_result/v1`, with: `run_id`,
`track`, `round`, `finished_at`, `engine_jail`, `scan.passed`, `score`
(`ceb.score.track_b/v1`: W/D/L, faults, `delta_elo`, `delta_elo_ci95`,
penalties, `final_delta_elo`), `feedback`, `metadata` (including the
`track_b` tree hashes and `software.stockfish_baseline = "sf_18/cb3d4ee"`),
`verified`, and a `signature` block.

Artifacts under `runs/<run-id>/track_b_official_<round>/`:

- `official_result.json` — public (the result above).
- `scan_report.json` — private (full scan findings).

Signing is symmetric HMAC-SHA256 keyed by `CEB_SIGNING_KEY`. With no key the
`signature.status` is `unsigned` and carries a "NO cryptographic authenticity"
note — see `docs/reproducibility.md`. A symmetric HMAC authenticates only to
holders of the same key; it is not public-key attestation.

## Engine jail for the candidate

`--engine-jail docker` is forwarded to `run_track_b_round`, which confines the
**candidate** engine in the Docker jail
(`bench/ceb/jail/`, image `chess-en-bench-jail:0.3` built by
`scripts/build_jail_image.sh`). The baseline build is operator-provided and
runs trusted on the host. The candidate must be a single executable inside its
workspace directory, or the jail request is rejected. Missing Docker or a
missing image produces an actionable `EngineJailError`. With `--engine-jail
none` (default) both engines run on the host.

## Verified vs diagnostic — what code enforces, what operators must do

`ceb track-b official run` always writes **`verified: false`**: the CLI calls
`run_official_track_b(..., verified=False)`. `verified=True` is reserved for
the hosted official worker; a direct CLI run is diagnostic.

**Enforced by code:**

- the scan must pass before any build;
- the baseline and candidate are built with the *same* build script and
  engine relpath;
- a build failure / missing engine aborts;
- tree hashes of both trees are recorded in metadata;
- UCI options (`Threads=1`, `Hash=16`) are sent to both engines by the round
  runner.

**Operator responsibility — NOT enforced by code:**

- supplying a real pinned-Stockfish build wrapper (e.g. a `ceb_build.sh`
  around `make -C src build`) for both trees;
- ensuring identical compiler flags between the baseline and candidate builds;
- `bench` / speed-sanity checks confirming the candidate is the pinned
  Stockfish with only whitelisted search changes.

The pipeline builds and plays whatever the build script produces; it does not
inspect compiler flags or run a `bench` sanity check. Treat CLI results as
diagnostic until they are reproduced through the operator-controlled hosted
path.

## Tests and CI

`tests/test_track_b_official.py` exercises the pipeline end to end with **tiny
fake source trees and a fake build script** that copies a bundled Python UCI
engine into place — there is **no real Stockfish and no compiler** involved.
Tests cover the happy path (builds, scores, records distinct tree hashes,
writes `official_result.json`), a forbidden-file rejection (scanner abort), and
a missing-build-script abort. CI does not run this pipeline; it runs only a
Track B toy *round* (`ceb track-b round run` with `BenchRandom`). No
Stockfish, Docker, or cloud runs in CI.
