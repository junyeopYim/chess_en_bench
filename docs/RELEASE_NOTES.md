# Release notes

Version numbers are the package version (`pyproject.toml`,
`bench/ceb/__init__.py`). Each release keeps prior CLI commands working.

## v0.3.0 — hosted official benchmark readiness

Theme: an engine must never read evaluator internals or hidden data; official
scores come only from hosted evaluator workers over clean snapshots, private
eval packs, fixed images, reproducible metadata, and meaningful evaluations.

- **Engine jail** (`--engine-jail docker`): confines only the untrusted
  engine — workspace mounted read-only at `/submission`, no repo / eval-pack /
  opponent mounts, `--network none`, read-only root + tmpfs, CPU/memory/pids
  limits, non-root, `no-new-privileges`. The evaluator stays trusted on the
  host. Legacy `--sandbox docker` (harness-in-container) remains for
  compatibility.
- **Hidden eval packs + jail together**: the private pack is read host-side by
  the evaluator and never mounted into the jail; positions reach the engine
  only as `position fen ...` UCI lines.
- **Artifact visibility model**: every artifact directory carries a manifest;
  `feedback.json` and `report.public.json` are public and sanitized, full
  reports / match logs / game text are private. A leak-scanner test asserts no
  hidden FEN, opening id, row id, move sequence, or host path appears in
  public artifacts.
- **Hidden-safe errors**: `SanitizedError` carries public/private messages;
  eval-pack and opening loaders take `hidden=True`; the CLI never prints
  tracebacks or hidden content to agent-facing output (`CEB_DEBUG=1` for
  operators).
- **Hosted pipeline** (`ceb hosted ...`, SQLite + local store): submissions
  are snapshotted (symlinks rejected) and hashed; the official worker is the
  only producer of `verified: true` results. It refuses to verify without a
  private eval pack, when the static scan fails, or when the strict gate
  fails.
- **Reproducibility metadata + signing**: every official result carries
  benchmark version, git commit, image digests, eval-pack / opponent-pool /
  opening-suite hashes, hardware/software, and seed. HMAC-SHA256 signing keyed
  by `CEB_SIGNING_KEY` (symmetric — documented as such); no key → explicit
  `unsigned`, never a false authenticity claim.
- **Eval modes**: `quick` (free, diagnostic, non-strict), `official_round`
  (budgeted, strict gate), `final_eval` (leaderboard-quality, strict, no
  budget cost). Scores carry an overall score rate, delta-Elo vs the pool with
  a 95% CI, per-opponent breakdown, fault counts, and opening coverage. The
  leaderboard uses the best final eval, else the best official round, never
  quick.
- **Anti-cheating scanners** (`ceb scan workspace`, `ceb scan track-b`):
  static detection of external chess libs/engines, network/process use,
  harness fingerprinting, oversized/binary/book/tablebase files, and symlink
  escapes; Track B adds diff-whitelist + content rules.
- **Hosted API**: `/api/hosted/...` runs, submissions, jobs, feedback,
  official result, verified-only leaderboard, and a public artifact resolver
  (deny-by-default, path-traversal-safe); admin POST endpoints gated by
  `CEB_ADMIN_TOKEN`.
- **Track B**: automated `ceb track-b round run` plus a source-first
  `ceb track-b official run` (scan → build baseline + candidate with the same
  script → paired matches → signed delta-Elo report). Optional `fastchess`
  adapter (`--runner fastchess`).
- **Draw adjudication**: threefold repetition, insufficient material
  (K vs K, K+B vs K, K+N vs K), and a configurable halfmove threshold.
- **CI**: adds scan, hosted SQLite smoke, and a Track B toy round across
  Python 3.10–3.12; no Stockfish/Docker/cloud dependencies.

## v0.2.0 — credible local benchmark

- Strict gate (`--strict`, perft mandatory); official rounds use it.
- Opening suites (`openings_public.jsonl`), rotated across opponents, paired
  colors.
- Official leaderboard excludes quick rounds (`--include-quick` diagnostic).
- Run-id inference for `runs/<id>/workspace`.
- Legacy `--sandbox docker` (harness-in-container) and hidden eval-pack
  interface.
- Automated Track B candidate-vs-baseline runner and the diff whitelist
  checker; GitHub Actions CI.

## v0.1.0 — local MVP

- Dependency-free chess oracle (validated against canonical perft counts),
  UCI client, public gate, six benchmark opponents, internal match runner,
  Elo/ladder/delta-Elo scoring, rounds + budget, FastAPI dashboard, Track B
  pin + scaffold.
