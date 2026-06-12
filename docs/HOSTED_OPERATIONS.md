# Hosted operations runbook (v0.3 MVP)

How an operator runs an official hosted evaluation of chess_en_bench v0.3.0.

This is an **MVP runbook**. The hosted pipeline is a single-node SQLite +
local-object-store design driven by a one-shot worker (`worker run-once`); the
API serves server-local workspace paths (no uploads); and result signing is
**symmetric HMAC**, not public-key attestation. It is good enough to produce
reproducible, verified results on a trusted operator machine — it is not a
hardened multi-tenant service. Sections below call out each MVP boundary.

All commands assume the repo root as the working directory and an editable
install in `.venv`. Replace `.venv/bin/ceb` with `ceb` if it is on your PATH.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,server]"   # 'server' (== 'hosted') extra pulls FastAPI/uvicorn
ceb doctor                        # confirms python deps, docker, git, stockfish
```

The hosted database and worker need only the Python standard library
(`sqlite3`, `hashlib`, `hmac`); the `server`/`hosted` extra is required only
for `ceb server start` and the HTTP API.

---

## 1. Build the Docker images

Official hosted evaluation confines the untrusted engine with
`--engine-jail docker`. Build that image first (tag `chess-en-bench-jail:0.3`):

```bash
bash scripts/build_jail_image.sh          # builds chess-en-bench-jail:0.3
```

The jail image (`infra/docker/engine_jail.Dockerfile`) is deliberately minimal:
a `python:3.12-slim` runtime and nothing of the benchmark. The `ceb` package is
**not** installed inside it, so a jailed engine cannot import evaluator code.
`docker_engine.py` runs each engine with `--network none`, `--read-only`,
`--tmpfs /tmp`, `--cpus 1`, `--memory 1g`, `--pids-limit 128`,
`--security-opt no-new-privileges`, a non-root host uid:gid, and mounts only
the submission workspace read-only at `/submission`.

The **legacy evaluator image** (`--sandbox docker`, harness-in-container) is a
separate, optional path and is **not** used by hosted evaluation. Build it only
if you also want to run the legacy sandbox:

```bash
bash scripts/build_evaluator_image.sh     # builds chess-en-bench-evaluator:0.2
```

If Docker or the jail image is missing, `--engine-jail docker` aborts with an
actionable `EngineJailError` telling you to run `scripts/build_jail_image.sh`.
You can verify a hosted run end-to-end with `--engine-jail none` (host
execution, trusted submissions only); the official policy is `docker`.

---

## 2. Run a local TOY hosted evaluation end-to-end

This walks the full pipeline against the bundled example submission and the
bundled fake private pack (`examples/eval_packs/tiny_private`). Use a throwaway
database so you do not touch `runs/hosted.sqlite`. `--quick-test-mode` selects a
tiny toy match profile (1 opponent, 2 games) for CI/smoke — **never** use it for
real scoring (see §3).

```bash
DB=/tmp/ceb_toy/hosted.sqlite

# (a) initialize the database + object store (<db>_store/ next to the db file)
.venv/bin/ceb hosted init --db "$DB"

# (b) snapshot + enqueue a submission (symlinks rejected; tree-hashed)
.venv/bin/ceb hosted submit \
    --track A \
    --workspace examples/submissions/minimal_uci_engine_python \
    --run-id toy-001 \
    --db "$DB"

# (c) drain one queued job: static scan -> strict gate vs the private pack ->
#     official_round with the pack -> public/private artifacts -> signed result.
#     Add --engine-jail docker for the jailed engine; --final-eval for a
#     final_eval instead of an official_round.
.venv/bin/ceb hosted worker run-once \
    --db "$DB" \
    --eval-pack examples/eval_packs/tiny_private \
    --quick-test-mode

# (d) inspect the recorded result and the verified-only leaderboard
.venv/bin/ceb hosted result show --run-id toy-001 --db "$DB"
.venv/bin/ceb hosted leaderboard --db "$DB" --track A
```

`worker run-once` prints a JSON status (`{"status": "done", ...,
"verified": true}`) and writes `official_result.json`
(schema `ceb.hosted.official_result/v1`, a public artifact) under
`<db>_store/<run-id>/job_<n>/`. The worker is the **only** producer of
`verified: true` results. It refuses to write a verified result — and the job is
marked `failed` with a sanitized reason — when:

- no private eval pack is given (`--eval-pack` is required to verify),
- the static scan fails, or
- the strict gate fails.

The hosted leaderboard (`db.verified_leaderboard`) is verified-only: best
`final_eval` per run, else best `official_round`; quick rounds never appear.

### Sign and verify the result

Signing is **symmetric HMAC-SHA256** keyed by `CEB_SIGNING_KEY`. With no key,
`worker run-once` still writes the result but stamps `signature.status:
"unsigned"` with a "NO cryptographic authenticity" note. Sign it explicitly by
setting the key in the environment:

```bash
RESULT=/tmp/ceb_toy/hosted_store/toy-001/job_1/official_result.json

# verify BEFORE signing -> authentic:false, signature_detail "unsigned result"
.venv/bin/ceb hosted verify-result --result "$RESULT"

# sign with the operator key, then verify with the same key -> authentic:true
CEB_SIGNING_KEY="change-me-operator-secret" \
    .venv/bin/ceb hosted sign-result   --result "$RESULT"
CEB_SIGNING_KEY="change-me-operator-secret" \
    .venv/bin/ceb hosted verify-result --result "$RESULT"

# verify with the wrong key -> authentic:false, "signature MISMATCH"
CEB_SIGNING_KEY="wrong-key" \
    .venv/bin/ceb hosted verify-result --result "$RESULT"
```

`verify-result` exits non-zero unless `authentic` is true (schema match, a valid
signature, and no missing metadata keys). For real runs, export
`CEB_SIGNING_KEY` for the worker too so results are signed at write time rather
than re-signed afterward.

---

## 3. Configure PRODUCTION game counts

`--quick-test-mode` is a hard-coded toy profile (1 opponent, 2 games, 30ms
movetime — `QUICK_TEST_MODE_CONFIG` in `bench/ceb/hosted/official_eval.py`) and
is for CI/smoke only. Real hosted scoring **omits** `--quick-test-mode`, which
makes the worker use the configured round modes from
`tracks/a_from_scratch/scoring.yaml`.

Edit the `final_eval` (and/or `official_round`) block there to set the
leaderboard-quality match volume:

```yaml
round_modes:
  final_eval:             # leaderboard-quality; strict gate; no budget cost
    opponents: [BenchRandom, BenchGreedyCapture, BenchMaterial1, BenchPST1, BenchMiniMax2, BenchAlphaBeta3]
    games_per_opponent: 8       # raise for tighter Elo confidence intervals
    movetime_ms: 200
    max_plies: 200
    openings_limit: 8           # first N openings of the resolved suite
    anchors: []                 # e.g. [SF18_UCI_Elo_1320, SF18_UCI_Elo_1600]
    anchors_required: true      # hosted: abort if a listed anchor is missing
```

- `games_per_opponent` / `openings_limit` drive run time and Elo precision.
- `anchors` enables limited-strength Stockfish anchor opponents defined under
  `anchor_opponents` (e.g. `SF18_UCI_Elo_1320`). Anchors send
  `UCI_LimitStrength` / `UCI_Elo` / `Threads=1` and require `stockfish` on PATH
  (`scripts/setup_stockfish.sh`).
- By default a missing anchor binary is **skipped with a progress note** so CI
  never depends on Stockfish. Set `anchors_required: true` (hosted policy) to
  make the round **abort** instead when a listed anchor is absent — this guards
  against silently scoring without the intended anchors.

Run a real final_eval through the worker (no `--quick-test-mode`, with the jail):

```bash
.venv/bin/ceb hosted worker run-once \
    --db runs/hosted.sqlite \
    --eval-pack /secure/path/to/private_pack \
    --engine-jail docker \
    --final-eval
```

The private eval pack is read host-side by the evaluator; positions reach the
jailed engine only as `position fen ...` UCI lines, so hidden packs combine
safely with `--engine-jail docker` (the pack directory is never mounted).

---

## 4. Serve the API

The HTTP API exposes the hosted endpoints and the dashboard. Point it at the
hosted database via `CEB_HOSTED_DB` (default `runs/hosted.sqlite`) and set
`CEB_ADMIN_TOKEN` to enable the admin POST endpoints:

```bash
export CEB_HOSTED_DB=runs/hosted.sqlite
export CEB_ADMIN_TOKEN="change-me-admin-token"
.venv/bin/ceb server start --host 127.0.0.1 --port 8000
```

**Admin POST endpoints** (require header `X-CEB-Admin-Token: $CEB_ADMIN_TOKEN`):

```bash
ADMIN=change-me-admin-token
curl -X POST localhost:8000/api/hosted/runs \
     -H "X-CEB-Admin-Token: $ADMIN" -H 'content-type: application/json' \
     -d '{"run_id":"api-001","track":"A"}'
curl -X POST localhost:8000/api/hosted/runs/api-001/submissions \
     -H "X-CEB-Admin-Token: $ADMIN" -H 'content-type: application/json' \
     -d '{"workspace":"examples/submissions/minimal_uci_engine_python"}'
curl -X POST localhost:8000/api/hosted/runs/api-001/jobs \
     -H "X-CEB-Admin-Token: $ADMIN" -H 'content-type: application/json' \
     -d '{"kind":"official_eval"}'
```

With no `CEB_ADMIN_TOKEN` configured, admin POSTs return **503**; a wrong/missing
token returns **403**. Submission `workspace` is a **server-local path** (MVP —
file uploads are future work). The API only enqueues jobs; you still run
`ceb hosted worker run-once` (the worker is not started by the server).

**Public GET endpoints** (no token):

```bash
curl localhost:8000/health
curl localhost:8000/api/hosted/runs/api-001
curl localhost:8000/api/hosted/runs/api-001/feedback
curl localhost:8000/api/hosted/runs/api-001/official-result
curl "localhost:8000/api/hosted/leaderboard?track=A"          # verified-only
curl localhost:8000/api/hosted/artifacts/<artifact_id>
```

The artifact endpoint is **deny-by-default**: it serves only artifacts whose DB
visibility is `public`; private/unknown ids and path-traversal attempts return
404 (or 400 for a malformed id). Bind to `127.0.0.1` behind your own
reverse proxy/TLS — the app does no auth beyond the admin token and ships no
rate limiting.

---

## 5. Signing key management (symmetric HMAC)

`CEB_SIGNING_KEY` is a shared secret used for HMAC-SHA256 over a canonical
serialization of each result (`bench/ceb/hosted/signing.py`). This is
**symmetric**: anyone with the key can both sign and verify, so it authenticates
results only to key-holders (the operator) — it is **not** public-key
attestation, and third parties cannot independently verify. Asymmetric signing
is explicitly future work.

Operator guidance:

- Treat the key as a secret: store it in a secrets manager or a non-world-
  readable env file, never in the repo, the database, or result files.
- Export `CEB_SIGNING_KEY` in the worker's environment so official results are
  signed at write time. Distribute the same key only to parties who must verify.
- Rotating the key invalidates verification of previously signed results — they
  show `signature MISMATCH` under the new key. Re-sign archived results with the
  new key if you need them to verify, or keep the retired key for verification.
- A result with no signature is never treated as authentic: `verify-result`
  returns `authentic: false` with `signature_detail` "unsigned result".

To make a stronger third-party-verifiable authenticity claim, you need
asymmetric signing — not available in v0.3.

---

## Notes / MVP boundaries

- **Single worker, manual drain.** `worker run-once` processes the oldest queued
  job and exits; run it in a loop or a scheduler for continuous operation. There
  is no built-in concurrency control across multiple workers on one database.
- **Track A only** for hosted submissions. Track B has its own pipeline
  (`ceb track-b official run`); its CLI runs are diagnostic (`verified: false`).
- **Reproducibility metadata** (`bench/ceb/hosted/metadata.py`) records the
  benchmark version, git commit, evaluator/jail image digests, eval-pack /
  opponent-pool / opening-suite hashes, hardware, software (incl.
  `stockfish_baseline: sf_18/cb3d4ee`), and the random seed. Image-digest fields
  are `null` when Docker is unavailable; commit the actual evaluator and jail
  images you run so digests are meaningful.
- **Sanitized errors.** Agent-facing output (CLI, feedback, public artifacts)
  never prints hidden FENs, moves, opening ids, or host paths. Set `CEB_DEBUG=1`
  for full operator tracebacks — never in an agent-facing service.
```