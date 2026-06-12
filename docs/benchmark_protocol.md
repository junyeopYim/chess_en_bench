# Benchmark Protocol (Track A run lifecycle)

This is the full lifecycle of a Track A run. The **local** path (sections 1–6)
is for iteration and diagnostics; the **hosted official** path (section 7) is
the authoritative path that produces verified, leaderboard-eligible results.
Source of truth: `bench/ceb/rounds/state.py` (budget and state),
`bench/ceb/rounds/round_runner.py` (round execution),
`bench/ceb/gate/gate_runner.py` (gate), `bench/ceb/eval_pack.py` (data packs),
`bench/ceb/scoring/track_a.py` (scoring and leaderboard),
`bench/ceb/hosted/` (hosted pipeline), `bench/ceb/storage/` (artifact
visibility), `bench/ceb/scan/` (static scan).

## 1. Prepare a workspace

```bash
ceb workspace prepare --track A --run-id demo [--runs-dir DIR]
```

Creates `runs/demo/workspace/`, copies the track prompt to
`runs/demo/instructions.md`, writes a workspace README, and initializes
`runs/demo/state.json` (schema `ceb.run.state/v1`) with `budget_total` taken
from `tracks/a_from_scratch/track.yaml` (`official_rounds: 3`). The agent
puts its submission in the workspace: an executable `engine`, or a `build.sh`
that produces one.

## 2. Iterate against the public gate (unlimited, free)

```bash
ceb gate run --track A --workspace runs/demo/workspace \
    [--strict] [--engine-jail docker] [--eval-pack DIR] [--sandbox docker] \
    [--json-out F] [--no-match]
```

Gate attempts are unlimited and never consume round budget. Checks run in
order; a hard failure skips the remaining heavy checks:

1. `format` — workspace has `engine` or `build.sh`
2. `build` — run `build.sh` if present (120 s limit)
3. `engine` — executable `./engine` exists after build
4. `handshake` — `uci`/`uciok`, `isready`/`readyok`
5. `position` — `position startpos` / `position fen` / moves accepted
6. `bestmove` — legal bestmove on the pack's FENs, validated by the oracle
7. `perft` — `go perft` extension vs oracle counts. Default mode: missing
   support is a warning, wrong counts fail. **Strict mode (`--strict`)**:
   perft is MANDATORY and a hard check — missing support or wrong counts
   fail the gate and skip the remaining checks.
8. `time` — bestmove returned within the `go movetime` budget
9. `mini_match` — 2 games vs BenchRandom with zero candidate faults
   (skipped with `--no-match`)

Exit code 0 = passed, 2 = failed. The JSON report (`ceb.gate.report/v1`,
with a `strict` field) is written to `--json-out`, or to
`runs/_gate/<workspace>-<timestamp>.json` by default. Bestmove/perft failure
details quote row ids only, never FENs, so hidden positions cannot leak.
A standalone `ceb gate run` defaults to non-strict and does not touch
`state.json`; the gate result is recorded into the run state whenever a
round runs (see below). `--engine-jail docker` runs the engine inside the jail
(section 6); the legacy `--sandbox docker` re-runs the whole gate in a
container instead.

## 3. Run a local round (the three eval modes)

```bash
ceb round run --track A --workspace runs/demo/workspace --round 1 \
    [--quick | --final-eval] [--run-id X] [--runs-dir DIR] \
    [--eval-pack DIR] [--engine-jail docker] [--sandbox docker]
```

If `--run-id` is omitted it is inferred from the workspace path
(`default_run_id`): a directory named `workspace` whose parent holds a
`state.json` uses the parent name (`runs/demo/workspace` → `demo`);
otherwise the workspace directory name is used. `--run-id` always overrides.

There are three eval modes (`round_modes` in `scoring.yaml`; defaults in
`round_runner.py`). Plain `ceb round run` is `official_round`; `--quick` is
`quick`; `--final-eval` is `final_eval`:

| Mode | Gate | Budget | Opponents | games/opp | openings | Leaderboard |
|---|---|---|---|---|---|---|
| `quick` | non-strict | free | BenchRandom, BenchMaterial1 | 2 | 2 | never |
| `official_round` | strict | consumes 1 of 3 | all six | 4 | 6 | eligible |
| `final_eval` | strict | none | all six | 8 | 8 | preferred |

The "all six" opponents are BenchRandom, BenchGreedyCapture, BenchMaterial1,
BenchPST1, BenchMiniMax2, BenchAlphaBeta3 (movetime 200 ms, 200 max plies).

Every round begins by **re-running the gate** so the round always starts from a
verified engine. The **strict** gate (`go perft` mandatory) is the precondition
for both official-grade modes; quick rounds run the non-strict gate. The result
is saved to `runs/<run_id>/gate_report.json` and recorded in `state.json`
(`gate.attempts`, `gate.passed`). If the gate fails, the round aborts and no
budget is touched.

The round's data comes from a resolved **eval pack**
(`bench/ceb/eval_pack.py`): public FENs, perft expectations, and the opening
suite (`tracks/a_from_scratch/public/`), optionally extended by an
operator-mounted private pack. An explicit `--eval-pack DIR` applies to any
gate or round; the `CEB_PRIVATE_EVAL_DIR` environment variable applies ONLY
to official-grade rounds and strict gates. No hidden data ships in this repo
(`examples/eval_packs/tiny_private/` documents the shape; see
`docs/EVAL_PACKS.md`).

Budget rules (`RunState.can_start_round` / `record_round`): quick and
`final_eval` are free; only `official_round` consumes budget (3 per run), and
the remaining-budget precondition is checked before any game is played. Every
**local** round is `verified: false` — self-reported diagnostics. Verified
results come only from the hosted worker (section 7).

Games start from the opening suite (canonical JSONL, every move
oracle-validated; `bench/ceb/match/openings.py`). Consecutive game pairs use
the same opening with colors swapped; the suite is rotated across opponents
(`rotate_suite`, offset `j * pairs`) so the round covers more openings than any
single match. Matches run on the internal runner
(`bench/ceb/match/internal_runner.py`): every move is oracle-validated, each
game is seeded deterministically (`base_seed = 1000 * round_number`), and games
are adjudicated as draws on max plies, the halfmove threshold
(`halfmove_draw_plies`, 100 = fifty-move / 150 = 75-move), threefold repetition
(clocks excluded from the position key), or conservative insufficient material
(K vs K, K+B vs K, K+N vs K only). Illegal moves, timeouts, and crashes lose the
game for the offending side and are tallied for penalties (illegal_move 30,
timeout 15, crash 25). Optional limited-strength **anchor opponents** (Stockfish
`UCI_Elo` levels, `anchor_opponents` in `scoring.yaml`) can be added to a mode's
`anchors` list; a missing engine binary skips the anchor with a progress note,
unless the mode sets `anchors_required` (hosted), in which case it aborts.

## 4. Per-round artifacts and visibility

```
runs/<run_id>/
  state.json                      # ceb.run.state/v1: budget, gate, round trajectory  [private]
  gate_report.json                # ceb.gate.report/v1 from the latest round's gate    [private]
  instructions.md                 # copy of the track prompt
  workspace/                      # the submission (if prepared via ceb workspace)
  round_N/
    artifacts_manifest.json       # ceb.artifacts.manifest/v1: per-file visibility
    feedback.json                 # ceb.round.feedback/v1: sanitized aggregates         [PUBLIC]
    report.public.json            # ceb.round.report.public/v1: sanitized round report  [PUBLIC]
    report.json                   # ceb.round.report/v1: full matches + score           [private]
    match_vs_<Opponent>.json      # full internal-runner match report                   [private]
    games_vs_<Opponent>.txt       # UCI-movetext game records                           [private]
```

Each artifact directory carries an `artifacts_manifest.json`
(`bench/ceb/storage/`); only files explicitly marked `public` are servable, and
unknown/unlisted files are treated as private (deny by default). The split:

- **Public:** `feedback.json` (per-opponent W/D/L, score rates, fault counts,
  penalty points, scores, generic advice — no FENs, moves, or opening ids) and
  `report.public.json` (`ceb.round.report.public/v1`, `verified:false`; omits
  workspace/host paths; `opening_ids` is null for private packs).
- **Private (operator-only):** `report.json` records `mode`, `strict_gate`,
  `eval_pack`, and `openings_used`, and embeds the round score
  (`ceb.score.track_a/v1`: per-opponent performance, an `overall` block with
  `score_rate` and `delta_elo_vs_pool` + 95% CI, faults, penalty points, ladder
  and final scores, and `opening_coverage`); `match_vs_*.json` and
  `games_vs_*.txt` carry full move detail.

## 5. Local leaderboard

```bash
ceb leaderboard compute --track A --results runs [--json-out F] [--include-quick]
```

Ranks each run by its best `final_eval`, else best `official_round` (the legacy
`official` mode key still counts); quick rounds are excluded by default and
`--include-quick` is a clearly-labelled diagnostic view. Every entry is
`verified:false` (self-reported). `ceb server start` serves a read-only
dashboard and `/api/leaderboard` over the same run artifacts (`server` extras).
For the authoritative, verified ranking see section 7 and
`docs/LEADERBOARD_GOVERNANCE.md`.

## 6. Engine jail and legacy sandbox

The **engine jail** (`--engine-jail docker`, `bench/ceb/jail/`) confines only
the untrusted engine; the evaluator stays trusted on the host. Build it once:

```bash
bash scripts/build_jail_image.sh                 # tag chess-en-bench-jail:0.3
ceb round run --track A --workspace <dir> --round 1 --eval-pack <pack> --engine-jail docker
```

The jailed engine runs from its workspace mounted read-only at `/submission`
with `--network none`, read-only root + tmpfs `/tmp`, `--cpus 1 --memory 1g
--pids-limit 128`, `no-new-privileges`, non-root (host uid:gid), stdio-only UCI.
There is no repo, eval-pack, or opponent mount, and the jail image omits the
`ceb` package so a jailed engine cannot import evaluator code. The hidden pack
is read host-side and reaches the engine only as `position fen ...` UCI lines,
so `--engine-jail docker` combines with `--eval-pack`. Workspace paths
containing `:` or newlines, and engine names containing `/`, are rejected.
Missing Docker or a missing image raises an actionable `EngineJailError`. The
default is `--engine-jail none`.

The legacy `--sandbox docker` (`bench/ceb/sandbox/`,
`infra/docker/evaluator.Dockerfile`, tag `chess-en-bench-evaluator:0.2`) re-runs
the whole harness in a container with the repo mounted read-only. It is retained
for compatibility, still rejects `--eval-pack`, and is **not** the hosted
official path.

## 7. Hosted official evaluation (the authoritative path)

The hosted pipeline (`bench/ceb/hosted/`) is the only path that produces
`verified: true` results. It is an MVP: single-node, SQLite + a local
`<db>_store/` object directory, symmetric (operator-only) signing, and
server-local submission paths.

```bash
bash scripts/build_jail_image.sh                       # jail image, once

ceb hosted init   --db runs/hosted.sqlite
ceb hosted submit --track A --workspace <dir> --run-id myrun --db runs/hosted.sqlite
ceb hosted worker run-once --db runs/hosted.sqlite \
    --eval-pack <private-pack> --engine-jail docker [--final-eval] [--quick-test-mode]
ceb hosted result show --run-id myrun --db runs/hosted.sqlite
ceb hosted leaderboard --track A --db runs/hosted.sqlite
```

Lifecycle (**submit → job → worker → verified result**):

1. **Submit.** `ceb hosted submit` snapshots the live workspace into the object
   store, **rejecting symlinks** and non-regular files, and tree-hashes the
   snapshot (`bench/ceb/hosted/submissions.py`). The worker only ever evaluates
   the snapshot, never the live workspace — this pins what was evaluated and
   blocks post-submission edits. A job (`official_eval`) is enqueued.
2. **Worker.** `ceb hosted worker run-once` drains the oldest queued job and
   runs `run_official_eval` (`bench/ceb/hosted/official_eval.py`):
   static scan (`ceb.scan.workspace/v1`) → strict gate against the private pack
   → `official_round` (or `final_eval` with `--final-eval`) with the private
   pack and optional engine jail → public/private artifacts → reproducibility
   metadata + signing → verified result. `--quick-test-mode` swaps in a tiny
   toy config for CI/smoke (the profile is recorded in the result).
3. **Refusal to verify.** The worker writes **no** verified result when there is
   no private eval pack, the static scan fails, or the strict gate fails. In
   those cases the job is marked failed with a sanitized reason and the run gets
   no verified result.
4. **Verified result.** On success the worker writes
   `official_result.json` (`ceb.hosted.official_result/v1`, a public artifact)
   with the score, sanitized feedback, the metadata block, and a signature; it
   records the result in the DB with `verified: true` and registers each
   artifact's visibility for API serving.

**Reproducibility metadata** (`bench/ceb/hosted/metadata.py`) records
`benchmark_version` (0.3.0), `git_commit`, evaluator and engine-jail image
digests, `eval_pack_id`, `eval_pack_hash` (sha256 of the pack dir),
`opponent_pool_hash` (sha256 of `opponents.py`), `opening_suite_hash`, hardware
(cpu model/cores, memory limit), software (python, platform, compiler,
fastchess, `stockfish_baseline: sf_18/cb3d4ee`), `random_seed`, and `verified`.
Fields that cannot be determined locally are explicit nulls.

**Signing** (`bench/ceb/hosted/signing.py`) is HMAC-SHA256 over a canonical
serialization, keyed by `CEB_SIGNING_KEY`. This is **symmetric** — only
key-holders can verify; it is not public-key attestation. With no key, results
are written `signature.status = "unsigned"` with an explicit "NO cryptographic
authenticity" note, and `ceb hosted verify-result` returns `authentic: false`.
A tampered result or a wrong key verifies as a mismatch.

```bash
ceb hosted sign-result   --result <official_result.json>   # re-sign with CEB_SIGNING_KEY
ceb hosted verify-result --result <official_result.json>   # ceb.hosted.verification/v1 verdict
```

**Hosted leaderboard** (`ceb hosted leaderboard`, `db.verified_leaderboard`,
`ceb.hosted.leaderboard/v1`) is verified-only: per run, best `final_eval` else
best `official_round`; quick never appears (the worker never marks quick
verified).

The same operations are exposed over HTTP (`bench/ceb/api/main.py`, `server`
extra): admin-gated POST `/api/hosted/runs`, `/runs/{id}/submissions`,
`/runs/{id}/jobs` (require `X-CEB-Admin-Token == CEB_ADMIN_TOKEN`; no token →
503, wrong → 403), and GET `/api/hosted/runs/{id}`, `/feedback`,
`/official-result`, `/leaderboard?track=A` (verified-only), and
`/artifacts/{id}` (serves only artifacts whose DB visibility is `public`;
private/unknown → 404, path traversal → 400/404). The DB path comes from
`CEB_HOSTED_DB` or `runs/hosted.sqlite`.

## Track B rounds

```bash
ceb track-b round run --candidate-engine X --baseline-engine Y \
    [--baseline-src D --candidate-src D] [--games N --movetime MS] \
    [--engine-jail docker] [--runner internal|fastchess]

ceb track-b official run --candidate-src <tree> [--baseline-src <tree>] \
    [--eval-pack DIR] [--engine-jail docker] \
    [--build-script ceb_build.sh] [--engine-relpath ceb_engine]
```

`round run` plays two binaries: diff whitelist check (a violation aborts before
any game) → UCI handshake → paired-opening alternating-color games with
`Threads=1 Hash=16` sent to both → delta-Elo scoring → `report.json`
(`ceb.track_b.round.report/v1`) plus sanitized `feedback.json`. `official run`
(`bench/ceb/track_b/official_pipeline.py`) is the source-first pipeline: scan
(`ceb.scan.track_b/v1`) → build baseline + candidate with the **same** build
script → paired matches → signed `ceb.track_b.official_result/v1`. CLI runs are
`verified: false` (diagnostic); real pinned-Stockfish builds with identical
flags and a bench sanity check are operator steps, not enforced by code. The
internal runner is the default and trusted reference; `--runner fastchess`
(`bench/ceb/match/fastchess_runner.py`) is an optional high-volume backend. See
`docs/track_b_stockfish_optimization.md` and
`docs/TRACK_B_OFFICIAL_PIPELINE.md`.
