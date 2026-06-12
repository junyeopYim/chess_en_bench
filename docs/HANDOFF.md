# Handoff

## Goal
chess_en_bench v0.3: hosted official benchmark readiness. Official scores are
produced only by a hosted evaluator worker from clean snapshots, private eval
packs, an isolated engine jail, reproducible signed metadata, and
statistically meaningful evaluations. The untrusted engine can never read
evaluator internals or hidden data.

## Current state (branch v0.3-hosted-benchmark)
All P0 and P1 items implemented and tested.

P0:
- Engine jail (`bench/ceb/jail/`): `--engine-jail docker` confines only the
  engine — workspace-only read-only mount, no repo/pack/opponent mounts,
  network-none, read-only root, resource limits, non-root, recursion-guarded.
- Hidden eval pack + jail combine safely (pack read host-side, never mounted).
- Artifact visibility model (`bench/ceb/storage/`): public `feedback.json` /
  `report.public.json`; private full reports/logs; manifest per directory.
- Hidden-safe errors (`bench/ceb/sanitize.py`, `hidden=` loaders); CLI prints
  no tracebacks/secrets (`CEB_DEBUG=1` for operators).
- Hosted pipeline (`bench/ceb/hosted/`, SQLite + store): snapshots, jobs,
  official worker = only source of `verified: true`. Refuses to verify without
  a private pack / on scan failure / on strict-gate failure.
- Reproducibility metadata + HMAC-SHA256 signing (`CEB_SIGNING_KEY`; explicit
  `unsigned` otherwise).
- Eval modes quick / official_round / final_eval with CI fields; leaderboard
  prefers final_eval, then official rounds, never quick.
- Anti-cheating scanners (`bench/ceb/scan/`): `ceb scan workspace|track-b`.
- Hosted API endpoints with deny-by-default public artifact serving and
  `CEB_ADMIN_TOKEN`-gated POSTs.

P1:
- Optional fastchess adapter (`--runner fastchess`).
- Track B source-first pipeline (`ceb track-b official run`).
- Draw adjudication: threefold repetition, insufficient material, configurable
  halfmove threshold.
- Stockfish UCI_Elo anchors wired into round config (graceful skip;
  `anchors_required` for hosted).

## Test results
- `pytest -q`: 180 passed, 3 skipped (Docker integration — opt-in via
  `CEB_DOCKER_TESTS=1`; verified locally with images built: 15 docker tests
  pass, jailed gate + jailed round + hosted worker all green).
- Acceptance + hosted smoke + Track B toy commands: all exit 0.

## Known limitations
- Result signing is symmetric (HMAC); public-key attestation is future work.
- Track B official pipeline builds via a per-tree `ceb_build.sh`; real
  pinned-Stockfish build wrappers and `bench`/speed sanity are operator-
  supplied (documented in docs/TRACK_B_OFFICIAL_PIPELINE.md).
- fastchess adapter folds faults into results (no per-fault attribution) and
  has no oracle PGN post-validation yet.
- Hosted backend is SQLite + local FS (single-node MVP); no auth beyond the
  admin token, no upload transport (submissions are server-local paths).
- `--eval-pack` is intentionally unsupported with the legacy `--sandbox docker`
  mode; use `--engine-jail docker` instead.

## Next steps
- Asymmetric (public-key) result signing + a published verification key.
- Real pinned-Stockfish build wrappers + `bench` sanity in the Track B
  official pipeline; wire it into the hosted worker for Track B jobs.
- Upload transport + authn for hosted submissions; multi-worker queue.
- fastchess PGN → oracle post-validation.
