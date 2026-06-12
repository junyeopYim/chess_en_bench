# Hosted architecture (v0.3)

How a Track A submission becomes a *verified* official result, and where the
trust boundary sits. This describes the current code; the changelog lives in
`docs/RELEASE_NOTES.md`.

The one invariant everything else serves: **the untrusted engine never reads
evaluator internals or hidden data, and a verified score is produced only by
the official worker.**

## Trust boundary

There are two sides, and they do not overlap.

**Evaluator controller — trusted, on the host.** This is the harness:
gate, round runner, oracle, scoring, eval-pack loading, scanner, hosted
pipeline, signing. It reads the *private* eval pack and the opponent pool,
runs matches, and writes both public and private artifacts. It runs as the
normal host process; nothing about it is sandboxed.

**Engine jail — untrusted, workspace-only.** The submission's UCI engine is
the only thing confined. Under `--engine-jail docker` it runs in a container
that sees *nothing but its own workspace*, mounted read-only at `/submission`.
No repository, no eval pack, no opponents, no other runs. It talks UCI over
stdin/stdout and that is its entire view of the world.

The eval pack stays host-side. Hidden positions reach the jailed engine only
as `position fen ...` UCI lines — the pack directory is never mounted. This is
why a private pack combines safely with the jail (`--eval-pack` works with
`--engine-jail docker`), unlike the legacy `--sandbox docker` mode (harness in
a container), which still rejects `--eval-pack`.

```
                         HOST  (trusted)                 │  JAIL (untrusted)
                                                         │
  private eval pack ──▶ evaluator controller            │
  opponents.py      ──▶  (gate, oracle, scoring,         │
                          round runner, signing)         │
                              │     ▲                     │
              position fen …  │     │  bestmove …         │
                  (UCI line)  ▼     │  (UCI line)         │
                          ┌─────────────────┐  stdin/out ┌──────────────────┐
                          │ engine_command  │ ─────────▶ │ docker run -i     │
                          │ (jail front-end)│ ◀───────── │  submission/engine│
                          └─────────────────┘            │  /submission (ro) │
                                                         │  --network none   │
   public artifacts ◀── feedback.json, report.public,    │  --read-only      │
   private artifacts ◀── report.json, match_vs_*, games  │  cpu/mem/pids cap │
                                                         │  non-root, nnp    │
```

The jail image (`infra/docker/engine_jail.Dockerfile`,
`chess-en-bench-jail:0.3`, built by `scripts/build_jail_image.sh`) is a plain
Python+bash runtime and deliberately does **not** install the `ceb` package,
so even a hostile engine inside the jail cannot import evaluator code. Docker
flags: `--network none --read-only --tmpfs /tmp --cpus 1 --memory 1g
--pids-limit 128 --security-opt no-new-privileges`, non-root
(`--user <host-uid:gid>`), `-i` for UCI. A workspace path containing `:` or a
newline is rejected; an `engine_name` containing `/` is rejected. Missing
Docker or a missing image raises an actionable `EngineJailError`.

## Data flow: one hosted official evaluation

```
  submit ──▶ snapshot + tree-hash ──▶ queue job
                                          │
                                          ▼
                          worker.run_once  (drains oldest job)
                                          │
                                          ▼
                    ┌─────────── official_eval ───────────┐
                    │ static scan (deny on fail)          │
                    │ strict gate vs PRIVATE pack         │
                    │ official_round | final_eval         │
                    │   (matches, engine jail optional)   │
                    │ artifacts: public / private split   │
                    │ metadata + HMAC signature           │
                    └──────────────┬──────────────────────┘
                                   ▼
                       verified result recorded
                                   │
                                   ▼
                       verified-only leaderboard
```

1. **Submit.** `ceb hosted submit` (or `POST /runs/{id}/submissions`) copies
   the live workspace into an immutable snapshot, rejecting symlinks and
   non-regular files, and computes a deterministic tree hash. The worker only
   ever evaluates the snapshot, so post-submission edits and symlink tricks
   cannot change what was scored. (`hosted/submissions.py`)
2. **Queue.** A `official_eval` job row is enqueued. (`hosted/db.py`)
3. **Worker.** `ceb hosted worker run-once` pulls the oldest queued job and
   calls `run_official_eval`. (`hosted/worker.py`, `hosted/official_eval.py`)
   The official worker is the *only* producer of `verified: true` results. It:
   - runs the static anti-cheating scan; a `fail` finding aborts;
   - runs the **strict** gate against the private eval pack;
   - runs an `official_round` (or `final_eval` with `--final-eval`), with the
     engine optionally jailed via `--engine-jail docker`;
   - splits artifacts into public and private (visibility manifest);
   - attaches reproducibility metadata and an HMAC signature;
   - records the verified result and registers each artifact's visibility.

   It **refuses to verify** — no verified result is written — when there is no
   private eval pack, the scan fails, or the strict gate fails. On any failure
   the job is marked `failed` with a sanitized public reason; full detail goes
   to private logs only.
4. **Leaderboard.** `db.verified_leaderboard` ranks verified results only:
   best `final_eval` per run, else best `official_round`. A `quick` round is
   never verified, so it never appears. Self-reported local CLI rounds carry
   `verified: false` and never reach this path.

Reproducibility metadata (`hosted/metadata.py`) records: `benchmark_version`
(0.3.0), `git_commit`, `evaluator_image_digest`, `engine_jail_image_digest`,
`eval_pack_id`, `eval_pack_hash` (sha256 of the pack dir), `opponent_pool_hash`
(sha256 of `opponents.py`), `opening_suite_hash`, `hardware`
(cpu_model/cpu_cores/memory_limit), `software`
(python/platform/compiler/fastchess/`stockfish_baseline: sf_18/cb3d4ee`),
`random_seed`, and `verified`. Fields that cannot be determined locally are
explicit `null`, never silently dropped.

## Components

| Concept | Module | What it does |
| --- | --- | --- |
| Engine jail front-end | `bench/ceb/jail/engine_jail.py` | Resolves jail mode (`none`/`docker`); `EngineJailError` on missing Docker/image |
| Docker jail backend | `bench/ceb/jail/docker_engine.py` | Builds `docker run` argv, validates workspace path / engine name, reaps stragglers |
| Static scanner (Track A) | `bench/ceb/scan/static_scan.py` | External chess libs, engines, network, subprocess, harness fingerprinting, oversized files, book/tablebase/NNUE, binaries, symlink escape |
| Track B scanner | `bench/ceb/scan/track_b_scan.py` | Diff whitelist + binary/NNUE payloads + fingerprinting + network/process + tablebase + symlinks |
| Artifact visibility | `bench/ceb/storage/artifacts.py` | `artifacts_manifest.json`; `public_artifacts()` is deny-by-default |
| Sanitized errors | `bench/ceb/sanitize.py` | `SanitizedError(public, private)`; withholds FENs/moves/paths from public text |
| Hosted DB | `bench/ceb/hosted/db.py` | SQLite tables (runs, submissions, jobs, results, artifacts); `verified_leaderboard` |
| Submission snapshots | `bench/ceb/hosted/submissions.py` | Copy workspace, reject symlinks, tree-hash |
| Official worker | `bench/ceb/hosted/worker.py` | Drains one queued job, records verified result + artifact visibility |
| Official eval pipeline | `bench/ceb/hosted/official_eval.py` | scan → strict gate → round/final → artifacts → metadata+sign; refuses to verify on precondition failure |
| Repro metadata | `bench/ceb/hosted/metadata.py` | Version, git commit, image digests, content hashes, hardware/software, seed |
| Signing | `bench/ceb/hosted/signing.py` | HMAC-SHA256 keyed by `CEB_SIGNING_KEY`; unsigned when no key |
| Verifier | `bench/ceb/hosted/verifier.py` | Signature + schema + metadata-completeness verdict |
| Hosted API | `bench/ceb/api/main.py` | Admin-gated POST, public-only GET; serves only artifacts marked public |
| Round runner | `bench/ceb/rounds/round_runner.py` | quick / official_round / final_eval; the trusted match loop calling `engine_command` |

## Artifact visibility

Every artifact directory carries an `artifacts_manifest.json` recording each
file's visibility; `public_artifacts()` returns only files *explicitly* marked
public — anything unlisted is treated as private (deny by default). For a
round:

- **public:** `feedback.json`, `report.public.json` (schema
  `ceb.round.report.public/v1`, `verified: false` for self-reported runs,
  `opening_ids` null for private packs; omits workspace/host paths and hidden
  opening ids). The hosted `official_result.json`
  (`ceb.hosted.official_result/v1`) and the top-level `feedback.json` written
  by the worker are also public.
- **private:** `report.json`, `match_vs_*.json`, `games_vs_*.txt`,
  `gate_report.json`, `scan_report.json` — start FENs, move lists, game text,
  gate detail against hidden data.

The worker registers each file's visibility in the DB so the API can serve it.

## Signing and verification

Signing is **symmetric** HMAC-SHA256 over a canonical JSON serialization,
keyed by `CEB_SIGNING_KEY`. This authenticates a result to anyone holding the
same key (the operator); it is **not** public-key attestation — third parties
cannot verify without the key. With no key, the result is written with
`signature.status = "unsigned"` and a note that it has NO cryptographic
authenticity, and `verify_result` returns `(False, "unsigned ...")`. A tampered
result or a wrong key yields a signature mismatch. (`hosted/signing.py`,
`hosted/verifier.py`)

## Sanitized error handling

Anything that might quote hidden data carries a public and a private message
(`SanitizedError`). `sanitize_exception()` returns the public text, or for an
unknown exception type the fixed string *"internal error (<Type>); details
withheld — operators can rerun with CEB_DEBUG=1"* (arbitrary messages may embed
FENs). Hidden eval-pack load errors quote only the file basename + row id +
"content withheld" — never FENs, moves, or paths. The CLI `main()` catches
everything, prints a sanitized one-liner, returns nonzero (3 for unknown), and
re-raises full tracebacks only when `CEB_DEBUG=1`. (`bench/ceb/sanitize.py`,
`bench/ceb/cli.py`)

## Hosted API surface

`bench/ceb/api/main.py` (requires the `server` extra). DB path from
`CEB_HOSTED_DB`, else `runs/hosted.sqlite`.

- **Admin-gated POST** (`X-CEB-Admin-Token` must equal `CEB_ADMIN_TOKEN`; no
  token configured → 503, wrong token → 403): `POST /api/hosted/runs`,
  `/runs/{id}/submissions`, `/runs/{id}/jobs`.
- **Public GET:** `/api/hosted/runs/{id}`, `/runs/{id}/feedback`,
  `/runs/{id}/official-result`, `/leaderboard?track=A` (verified-only),
  `/artifacts/{id}` (serves only artifacts whose DB visibility is `public`;
  private/unknown → 404, path traversal → 400/404). `/health` is unchanged.

## Running it

```bash
# Build the engine jail image (once)
bash scripts/build_jail_image.sh

# Hosted pipeline end to end (SQLite + local object store)
ceb hosted init   --db runs/hosted.sqlite
ceb hosted submit --track A \
    --workspace examples/submissions/minimal_uci_engine_python \
    --run-id demo --db runs/hosted.sqlite
ceb hosted worker run-once --db runs/hosted.sqlite \
    --eval-pack <private-pack> --engine-jail docker        # add --final-eval for leaderboard quality
ceb hosted result show --run-id demo --db runs/hosted.sqlite
ceb hosted leaderboard --db runs/hosted.sqlite --track A

# Sign / verify a result (needs CEB_SIGNING_KEY set to verify authenticity)
ceb hosted sign-result   --result <official_result.json>
ceb hosted verify-result --result <official_result.json>
```

For CI/smoke without Stockfish or Docker, add `--quick-test-mode` to the
worker (a tiny toy profile, recorded as `config_profile: quick-test`).

## MVP seam: where this becomes a real service

The hosted pipeline is an MVP, not a production service. Be honest about the
two seams:

- **SQLite + local filesystem backend.** State lives in one SQLite file
  (`hosted/db.py`) and a sibling `<db>_store/` object directory. There is no
  network storage, no replication, no concurrent-writer story. For a real
  deployment, `hosted/db.py` and `hosted/submissions.py` (snapshot storage) are
  the swap points for a real database and object store.
- **Single-node, single-job worker.** `worker.run_once` drains exactly one
  queued job per invocation in the same process; there is no distributed
  queue, no leasing/retry, no horizontal scaling. The DB `jobs` table and
  `next_queued_job` are the seam for a real queue.
- **Submission intake.** The API takes a server-local workspace path; file
  uploads are future work.
- **Signing.** Symmetric HMAC only (see above); asymmetric public-key
  attestation is future work.

The interfaces (DB accessors, snapshot+hash, worker `run_once`, artifact
visibility) are stable; the storage and execution backends behind them are
what a real service would replace.
