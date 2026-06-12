# chess_en_bench

A benchmark platform for LLM coding agents that **build chess engines from
scratch** (Track A) or **optimize Stockfish's search** (Track B) under
controlled, reproducible conditions.

**v0.3 makes the benchmark ready to run as a hosted official evaluation.** An
untrusted engine can be confined to a Docker **engine jail** that sees only its
own workspace — never the repository, the opponents, or the hidden eval pack —
while the trusted evaluator stays on the host. A **hosted pipeline** snapshots
each submission, runs a static scan + strict gate + scored round against a
private pack, and is the **only** producer of `verified: true` results. Results
carry **reproducibility metadata** and an HMAC signature, and artifacts are
split into sanitized **public** and operator-only **private** views. This is an
MVP: it is single-node (SQLite + a local object store), signing is symmetric
(operator-verifiable, not public-key attestation), and uploads are server-local
paths. All v0.2 commands still work unchanged.

## Quickstart

```bash
git clone https://github.com/junyeopYim/chess_en_bench.git
cd chess_en_bench
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,server]"

ceb doctor                       # environment diagnosis
pytest -q                        # 180 passed + 3 skipped (Docker tests opt-in: CEB_DOCKER_TESTS=1)
```

Run the public gate and a quick round against the bundled example engine:

```bash
ceb gate run  --track A --workspace examples/submissions/minimal_uci_engine_python
ceb gate run  --track A --workspace examples/submissions/minimal_uci_engine_python --strict
ceb round run --track A --workspace examples/submissions/minimal_uci_engine_python --round 1 --quick
ceb round run --track A --workspace examples/submissions/minimal_uci_engine_python --round 1 --final-eval
ceb scan workspace --track A --workspace examples/submissions/minimal_uci_engine_python
ceb leaderboard compute --track A --results runs                 # official + final, quick excluded
ceb leaderboard compute --track A --results runs --include-quick # diagnostic view
ceb server start --host 127.0.0.1 --port 8000   # dashboard at http://127.0.0.1:8000/
```

## Engine jail (untrusted-engine isolation)

The engine jail confines **only** the submission's UCI engine; the evaluator
stays trusted on the host and reads any hidden pack itself. The jailed engine
sees nothing but its workspace, mounted **read-only** at `/submission` —
`--network none`, read-only root + tmpfs `/tmp`, `--cpus 1 --memory 1g
--pids-limit 128`, `--security-opt no-new-privileges`, non-root, stdio-only UCI.
There is no repo, eval-pack, or opponent mount, and the jail image deliberately
does **not** install the `ceb` package, so a jailed engine cannot import
evaluator code. Hidden packs combine safely: positions reach the jail only as
`position fen ...` lines over stdin, so `--eval-pack` works **with**
`--engine-jail docker` (unlike the legacy `--sandbox docker`).

```bash
bash scripts/build_jail_image.sh                 # builds chess-en-bench-jail:0.3
ceb gate run  --track A --workspace <dir> --engine-jail docker
ceb round run --track A --workspace <dir> --round 1 --eval-pack <private-pack> --engine-jail docker
```

`--engine-jail` defaults to `none` (host execution; trusted/local use). Missing
Docker or a missing image raises an actionable error. The legacy
`--sandbox docker` mode (whole harness in a container, with the repo mounted) is
still available but is **not** the hosted official path, and it still rejects
`--eval-pack`.

## Hosted official evaluation (MVP)

The hosted pipeline is the **authoritative** path for verified results. The
official worker is the only code that writes `verified: true`: it runs a static
scan → strict gate against the private pack → `official_round` (or `final_eval`)
with the private pack and optional engine jail → public/private artifacts →
metadata + signing. It **refuses to verify** (writes no verified result) when
there is no private eval pack, the scan fails, or the strict gate fails. The
default store is SQLite (`runs/hosted.sqlite`) plus a `<db>_store/` object
directory.

```bash
bash scripts/build_jail_image.sh                 # jail image, once

ceb hosted init   --db runs/hosted.sqlite
ceb hosted submit --track A --workspace <dir> --run-id myrun --db runs/hosted.sqlite
# snapshots the workspace (symlinks rejected), tree-hashes it, enqueues a job

ceb hosted worker run-once --db runs/hosted.sqlite \
    --eval-pack <private-pack> --engine-jail docker     # add --final-eval for leaderboard-quality
ceb hosted result show  --run-id myrun --db runs/hosted.sqlite
ceb hosted leaderboard  --track A --db runs/hosted.sqlite   # verified results only; quick never appears
```

Verify a result file later: `ceb hosted verify-result --result <official_result.json>`
(set `CEB_SIGNING_KEY` to sign/verify; without a key, results are explicitly
`unsigned` and claim no cryptographic authenticity). The same operations are
exposed over HTTP under `/api/hosted/...` (admin POST endpoints gated by
`CEB_ADMIN_TOKEN`; public GET endpoints serve only public artifacts). See
[docs/benchmark_protocol.md](docs/benchmark_protocol.md),
[docs/reproducibility.md](docs/reproducibility.md), and
[docs/RESULT_SIGNING.md](docs/RESULT_SIGNING.md).

## The two tracks

**Track A — from-scratch engine.** The evaluated agent receives a public spec
([specs/uci_minimal.md](specs/uci_minimal.md)), a public correctness gate, and
example FEN/perft data ([tracks/a_from_scratch/public/](tracks/a_from_scratch/public/)).
It must produce a self-contained UCI engine. The gate may be run **unlimited**
times. Evaluation uses three modes — `quick` (free, diagnostic), `official_round`
(consumes 1 of 3 budget units, strict gate), and `final_eval` (strict gate, no
budget cost, leaderboard-quality). Rounds play the engine against a ladder of
benchmark-owned opponents (BenchRandom … BenchAlphaBeta3) and score it with an
Elo-style ladder rating minus fault penalties. See
[docs/track_a_from_scratch.md](docs/track_a_from_scratch.md).

**Track B — Stockfish search optimization.** The agent edits only
search-related files of a **pinned** baseline (Stockfish 18, tag `sf_18`,
commit `cb3d4ee` — never a moving branch) under a diff whitelist, and is scored
by candidate-vs-baseline delta Elo. `ceb track-b round run` plays a binary
candidate against a binary baseline; `ceb track-b official run` is the
source-first path (scan → build baseline + candidate with the **same** build
script → paired matches → signed `ceb.track_b.official_result/v1`). See
[docs/track_b_stockfish_optimization.md](docs/track_b_stockfish_optimization.md)
and [docs/TRACK_B_OFFICIAL_PIPELINE.md](docs/TRACK_B_OFFICIAL_PIPELINE.md).

```bash
bash scripts/setup_stockfish.sh   # optional: fetch the pinned baseline (GPLv3, gitignored)
ceb track-b status
ceb scan track-b --baseline-src <tree> --candidate-src <tree>
ceb track-b round run --candidate-engine <path> --baseline-engine <path> \
    --baseline-src <tree> --candidate-src <tree>
ceb track-b official run --candidate-src <tree> [--baseline-src <tree>] \
    [--eval-pack <dir>] [--engine-jail docker]
```

`ceb track-b round run` and `official run` are diagnostic (`verified: false`):
real pinned-Stockfish builds with identical flags and a bench sanity check are
operator steps, not enforced by code. The internal Python runner is the default
and trusted reference; `--runner fastchess` is an optional high-volume backend.

## How an evaluation runs

1. `ceb workspace prepare --track A --run-id myrun` — creates `runs/myrun/`;
   `round run` on `runs/myrun/workspace` infers the run id automatically.
2. The agent iterates: edit engine → `ceb gate run …` → read the JSON report →
   repeat. Gate attempts are free and unlimited.
3. **Local diagnostic round:** `ceb round run --track A --workspace … --round 1`
   (`--quick` for a free smoke round, `--final-eval` for a leaderboard-quality
   one). Official-grade rounds re-run the **strict** gate (perft mandatory),
   start games from the opening suite, and may consume an operator-mounted
   hidden eval pack (`--eval-pack` / `CEB_PRIVATE_EVAL_DIR`). Every local round
   is `verified: false` (self-reported).
4. **Hosted official round:** `ceb hosted submit` then `ceb hosted worker
   run-once` produces the only `verified: true` results; the hosted leaderboard
   ranks them (best `final_eval`, else best `official_round`; quick never
   appears).

Details: [docs/benchmark_protocol.md](docs/benchmark_protocol.md) and
[docs/agent_protocol.md](docs/agent_protocol.md).

## Repository layout

| Path | Contents |
| --- | --- |
| `bench/ceb/` | Python package: chess oracle, UCI client, gate, match runner, openings, eval packs, scoring, rounds, CLI |
| `bench/ceb/jail/` | Engine jail: `engine_jail.py` (front-end), `docker_engine.py` (Docker backend) — confines only the untrusted engine |
| `bench/ceb/storage/` | Artifact visibility model (`artifacts_manifest.json`; public is deny-by-default) |
| `bench/ceb/scan/` | Static anti-cheating scanners (`scan workspace`, `scan track-b`) |
| `bench/ceb/hosted/` | Hosted pipeline: SQLite db, submissions, official worker, metadata, signing, verifier |
| `bench/ceb/sanitize.py` | Hidden-safe errors (`SanitizedError`, `sanitize_exception`) |
| `bench/ceb/match/fastchess_runner.py` | Optional fastchess backend (internal runner is the default reference) |
| `bench/ceb/track_b/official_pipeline.py` | Track B source-first pipeline (scan → build → paired matches → signed result) |
| `bench/ceb/sandbox/` | Legacy harness-in-container `--sandbox docker` (compat; not the hosted path) |
| `tracks/` | Track configs, public data (incl. `openings_public.jsonl`), prompts, scoring/penalty tables |
| `specs/` | Normative contracts (UCI subset, perft extension, submission, feedback, forbidden behaviors) |
| `docs/` | Protocol, scoring, reproducibility, signing, eval-pack, leaderboard-governance, security docs |
| `examples/submissions/` | A minimal passing engine and intentionally broken engines |
| `examples/eval_packs/tiny_private/` | Fake demo hidden-pack showing the operator interface |
| `infra/docker/engine_jail.Dockerfile` | Engine jail image (`scripts/build_jail_image.sh`, tag `chess-en-bench-jail:0.3`) |
| `infra/docker/evaluator.Dockerfile` | Legacy sandbox image (`scripts/build_evaluator_image.sh`) |
| `tests/` | pytest suite (canonical perft counts included); CI runs it on 3.10–3.12 |
| `runs/`, `artifacts/` | Local outputs (gitignored) |

## Design notes

- The **oracle** (`bench/ceb/chess/`) is dependency-free and validated against
  canonical perft counts; it adjudicates every move in every game. v0.3 adds
  threefold repetition, conservative insufficient-material (K vs K, K+B vs K,
  K+N vs K), and a configurable halfmove draw threshold.
- Submitted engines are **untrusted**: argv-only spawning, timeouts on every
  read, bounded output intake, process-group kill, plus the optional engine
  jail. See [docs/security.md](docs/security.md).
- **Verified vs unverified:** only the hosted worker writes `verified: true`.
  Local rounds and direct Track B CLI runs are self-reported diagnostics.
- Everything machine-readable uses versioned JSON schemas
  (`ceb.gate.report/v1`, `ceb.round.report.public/v1`,
  `ceb.hosted.official_result/v1`, `ceb.scan.workspace/v1`, …); see
  [docs/overview.md](docs/overview.md).

License: MIT (see [LICENSE](LICENSE)); Stockfish is GPLv3 and is **not**
distributed with this repository (see [NOTICE](NOTICE)).
