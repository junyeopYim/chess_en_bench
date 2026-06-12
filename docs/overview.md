# chess_en_bench — Overview

chess_en_bench is a benchmark platform for LLM coding agents that build or
optimize chess engines. An agent gets a workspace, explicit instructions, and
public test data; the harness verifies the engine through a correctness gate,
plays seeded matches from a validated opening suite against a fixed opponent
pool, and turns the results into Elo-based scores and a leaderboard.

v0.3 makes the benchmark ready to run as a **hosted official evaluation**. The
untrusted engine can be confined to a Docker **engine jail** while the trusted
evaluator stays on the host and reads any hidden eval pack; a single-node
**hosted pipeline** (SQLite + a local object store) snapshots each submission
and is the only producer of `verified: true` results. This is an MVP — single
node, symmetric (operator-only) signing, server-local submission paths — and
every v0.2 command still works.

## The two tracks

**Track A — from-scratch engine** (`tracks/a_from_scratch/`). The agent builds
a UCI chess engine from nothing. The workspace must contain an executable
`engine` (or a `build.sh` that produces one). Unlimited public gate attempts
precede evaluation. Every official-grade round first re-runs the **strict**
gate (the `go perft` extension is mandatory there), then plays the candidate
against six bundled opponents (BenchRandom 400 up to BenchAlphaBeta3 1400
nominal Elo) and scores it as a ladder rating minus fault penalties. Optional
Stockfish `UCI_Elo` anchor opponents can be enabled in `scoring.yaml`; they are
skipped gracefully when the binary is absent, unless a mode sets
`anchors_required` (hosted), in which case a missing anchor aborts the round.

**Track B — Stockfish search optimization** (`tracks/b_stockfish_opt/`). The
agent may modify only search-related files of a pinned Stockfish baseline
(Stockfish 18, tag `sf_18`, commit `cb3d4ee` — never a moving branch, see
`stockfish.lock`). Scoring is delta Elo of candidate vs baseline with a
confidence interval (`ceb.score.track_b/v1`). `ceb track-b round run` plays a
binary candidate against a binary baseline (diff whitelist → handshake →
paired-opening games → delta-Elo report). `ceb track-b official run` is the
source-first pipeline: scan → build baseline + candidate with the **same** build
script → paired matches → signed `ceb.track_b.official_result/v1`. CLI runs are
diagnostic (`verified: false`); the internal runner is the trusted reference and
`--runner fastchess` is an optional high-volume backend.

## Eval modes

Track A rounds run in one of three modes (`round_modes` in
`tracks/a_from_scratch/scoring.yaml`; defaults in
`bench/ceb/rounds/round_runner.py`):

- **quick** — free, diagnostic, non-strict gate; 2 games/opponent, first 2
  openings. Never consumes budget and never appears on a leaderboard.
- **official_round** — strict gate; consumes one of 3 budget units; 4
  games/opponent, first 6 openings.
- **final_eval** — strict gate; leaderboard-quality; 8 games/opponent, first 8
  openings; does **not** consume round budget (hosted policy decides when it
  runs).

`compute_leaderboard` (and the hosted leaderboard) rank by best `final_eval`,
else best `official_round`, never `quick`; the legacy `official` mode key still
counts. `--include-quick` is a clearly-labelled diagnostic view only.

## Engine jail vs legacy sandbox

Two different isolation mechanisms exist and are not interchangeable:

- **Engine jail** (`--engine-jail docker`, `bench/ceb/jail/`,
  `infra/docker/engine_jail.Dockerfile`, tag `chess-en-bench-jail:0.3`). Confines
  **only** the untrusted engine. The evaluator stays trusted on the host, reads
  the hidden pack, runs the oracle and scoring; the engine sees only its
  workspace, mounted read-only at `/submission`, with `--network none`,
  read-only root + tmpfs `/tmp`, `--cpus 1 --memory 1g --pids-limit 128`,
  `no-new-privileges`, non-root, stdio-only UCI. No repo, eval-pack, or opponent
  mount. The jail image intentionally omits the `ceb` package so a jailed engine
  cannot import evaluator code. Because the pack is read host-side and reaches
  the engine only as `position fen ...` UCI lines, `--eval-pack` works together
  with `--engine-jail docker`. This is the hosted official isolation.
- **Legacy sandbox** (`--sandbox docker`, `bench/ceb/sandbox/`,
  `infra/docker/evaluator.Dockerfile`, tag `chess-en-bench-evaluator:0.2`).
  Re-runs the whole harness inside a container with the repo mounted read-only.
  Retained for compatibility; it still rejects `--eval-pack` and is **not** the
  hosted official path.

The default for both is `none` (host execution; trusted/local use).

## Verified vs unverified results

Only the hosted official worker (`bench/ceb/hosted/worker.py`) writes
`verified: true`. It runs static scan → strict gate against the private pack →
`official_round`/`final_eval` with the private pack and optional engine jail →
public/private artifacts → metadata + signing, and **refuses to verify** when
there is no private eval pack, the scan fails, or the strict gate fails. Local
`ceb round run` results and direct `ceb track-b` runs are always
`verified: false` (self-reported diagnostics). The verified-only hosted
leaderboard and the public API surface enforce this split. See
[LEADERBOARD_GOVERNANCE.md](LEADERBOARD_GOVERNANCE.md).

## Design principles

- **Explicit instructions.** Each track ships a `prompt.md`; `ceb workspace
  prepare` copies it into the run as `instructions.md`. No implicit rules.
- **Structured, machine-readable outputs.** Every artifact is versioned JSON
  (see the schema list below). Agents and operators parse results instead of
  scraping text.
- **Public data shipped, hidden data optional.** Gate FENs, perft counts, and
  the oracle-validated JSONL opening suite live under `tracks/*/public/`.
  Operators may mount a private eval pack (`--eval-pack <dir>`, or
  `CEB_PRIVATE_EVAL_DIR` for official-grade rounds and the strict gate); the
  pack is read host-side and never mounted into the engine jail.
  `examples/eval_packs/tiny_private/` documents the shape (no real hidden data
  is committed). See [EVAL_PACKS.md](EVAL_PACKS.md).
- **Iterative gate → round loop.** Gate attempts are unlimited and free. The
  standalone public gate and quick rounds are non-strict smoke tests;
  official-grade rounds always run the strict gate.
- **Artifact visibility (deny by default).** Every artifact directory carries
  an `artifacts_manifest.json` (schema `ceb.artifacts.manifest/v1`); only files
  explicitly marked `public` are servable. `feedback.json` and
  `report.public.json` (schema `ceb.round.report.public/v1`; `verified:false`;
  hidden opening ids nulled for private packs; no host/workspace paths) are
  public. `report.json`, `match_vs_*.json`, and `games_vs_*.txt` are private
  operator artifacts.
- **Hidden-safe errors.** `bench/ceb/sanitize.py` gives errors separate
  public/private messages; hidden eval-pack and opening loaders take
  `hidden=True` and quote only a file basename + row id + "content withheld",
  never FENs, moves, or paths. The CLI catches everything, prints a sanitized
  one-liner, and re-raises full tracebacks only under `CEB_DEBUG=1`.
- **Reproducible run metadata.** Each run persists `state.json`; games are
  seeded per round (`base_seed = 1000 * round_number`), colors alternate per
  opening pair, the suite is rotated across opponents. Official results embed a
  metadata block (benchmark version, git commit, image digests, eval-pack /
  opponent-pool / opening-suite hashes, hardware/software, seed). See
  [reproducibility.md](reproducibility.md).
- **Untrusted-code handling.** Engines are spawned argv-only (never
  `shell=True`), reads have timeouts, stdout is bounded, processes die by
  process-group SIGTERM/SIGKILL. The **engine jail** additionally confines the
  engine to a no-network, read-only, resource-capped container; the legacy
  `--sandbox docker` mode runs the whole harness in a container. See
  [security.md](security.md).

## JSON schemas

| Schema | Where |
|---|---|
| `ceb.run.state/v1` | per-run `state.json` |
| `ceb.gate.report/v1` | gate reports |
| `ceb.round.report/v1` | full (private) round report |
| `ceb.round.report.public/v1` | sanitized public round report |
| `ceb.round.feedback/v1` | agent-facing feedback |
| `ceb.score.track_a/v1` | Track A round score |
| `ceb.score.track_b/v1` | Track B delta-Elo score |
| `ceb.track_b.round.report/v1` | Track B round report |
| `ceb.track_b.feedback/v1` | Track B feedback |
| `ceb.track_b.official_result/v1` | Track B source-first official result |
| `ceb.leaderboard/v1` | local (self-reported) leaderboard |
| `ceb.hosted.official_result/v1` | hosted verified result |
| `ceb.hosted.leaderboard/v1` | verified-only hosted leaderboard |
| `ceb.hosted.verification/v1` | result-verification verdict |
| `ceb.scan.workspace/v1` | Track A static scan report |
| `ceb.scan.track_b/v1` | Track B candidate scan report |
| `ceb.artifacts.manifest/v1` | per-directory artifact visibility manifest |

The `ceb.score.track_a/v1` score now also carries an `overall` block
(`games`, `wins`, `draws`, `losses`, `score_rate`, `delta_elo_vs_pool`,
`delta_elo_ci95`) and `opening_coverage`.

## Repository layout

| Path | Contents |
|---|---|
| `bench/ceb/` | Python package: `cli.py`, `eval_pack.py`, `sanitize.py`, `gate/`, `match/` (incl. `openings.py`, optional `fastchess_runner.py`), `rounds/`, `scoring/`, `chess/` (internal oracle), `uci/`, `track_b/`, `api/` |
| `bench/ceb/jail/` | Engine jail: `engine_jail.py` (front-end), `docker_engine.py` (Docker backend) |
| `bench/ceb/storage/` | Artifact visibility model (`artifacts.py`) |
| `bench/ceb/scan/` | Static scanners (`static_scan.py`, `track_b_scan.py`) |
| `bench/ceb/hosted/` | Hosted pipeline: `db.py`, `submissions.py`, `worker.py`, `official_eval.py`, `metadata.py`, `signing.py`, `verifier.py` |
| `bench/ceb/sandbox/` | Legacy harness-in-container `--sandbox docker` runner |
| `tracks/a_from_scratch/` | Track A prompt, `track.yaml`, `scoring.yaml`, `public/` (FENs, perft, `openings_public.jsonl`, gate config) |
| `tracks/b_stockfish_opt/` | Track B prompt, `stockfish.lock`, path lists, `patch_policy.yaml`, `public/` (incl. `quick_openings.jsonl`) |
| `specs/` | Protocol and contract specs (submission contract, UCI perft extension) |
| `docs/` | This documentation |
| `scripts/` | `setup_dev.sh`, `setup_stockfish.sh`, `run_public_gate.sh`, `build_evaluator_image.sh`, `build_jail_image.sh` |
| `examples/` | `submissions/` (working + broken engines), `eval_packs/tiny_private/` (fake demo pack used by tests) |
| `infra/docker/` | `engine_jail.Dockerfile` (jail image, tag `chess-en-bench-jail:0.3`) and `evaluator.Dockerfile` (legacy sandbox image) |
| `.github/workflows/ci.yml` | CI on Python 3.10–3.12: pytest, doctor, gate, quick-round smoke, scan, hosted SQLite smoke, Track B toy round (no Stockfish, Docker, or cloud) |
| `web/static/` | Dashboard frontend served by `ceb server start` |
| `tests/` | pytest suite (180 passed + 3 skipped; Docker integration tests opt-in via `CEB_DOCKER_TESTS=1`) |
| `runs/` | Run artifacts: `runs/<run_id>/...`, ad-hoc gate reports in `runs/_gate/`, hosted DB + `<db>_store/` |
| `artifacts/` | Miscellaneous build/eval artifacts |

## Quickstart (5 commands)

```bash
bash scripts/setup_dev.sh && . .venv/bin/activate   # venv + pip install -e ".[dev,server]"

ceb doctor                                          # check environment
ceb workspace prepare --track A --run-id demo       # creates runs/demo/workspace
ceb gate run --track A --workspace runs/demo/workspace        # unlimited attempts
ceb round run --track A --workspace runs/demo/workspace --round 1 --quick  # free smoke round
ceb leaderboard compute --track A --results runs    # official + final, quick excluded
```

The CLI is installed as the console script `ceb` and is also runnable as
`python -m ceb.cli`. A prepared workspace at `runs/demo/workspace` infers run
id `demo`; `--run-id` always overrides. Add `--strict` to the gate to preview
the official-round check, `--final-eval` to the round for a leaderboard-quality
evaluation, and `--include-quick` to the leaderboard for a diagnostic view. For
untrusted engines, build the jail once (`bash scripts/build_jail_image.sh`) and
pass `--engine-jail docker` (it combines with `--eval-pack`). Core
gate/match/scoring need only the Python standard library; FastAPI/uvicorn are
optional extras for `ceb server start`.

For the full run lifecycle, budget rules, and the hosted official path, see
[benchmark_protocol.md](benchmark_protocol.md).
