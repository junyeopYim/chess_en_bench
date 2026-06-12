# Security model (v0.3)

chess_en_bench evaluates code it did not write. Both tracks accept untrusted
submissions: Track A engines (and their `build.sh`) and Track B candidate
patches are produced by the LLM agents under evaluation. This document is the
formal trust model for the hosted official benchmark: what we defend, how the
engine jail enforces it, and — explicitly — what v0.3 does NOT yet enforce.

For the operator-facing "how do I run this safely" guide, see
[security.md](security.md). This document is the *why* behind that guidance.

## Threat

The adversary is an untrusted submission that wants to win the benchmark by
any means other than playing good chess from scratch:

- **Untrusted engine code (Track A).** An arbitrary native or interpreted
  program speaking UCI. It may try to read the hidden eval pack, opponents,
  or evaluator source; reach the network to download a stronger engine or an
  online oracle; spawn processes; exhaust CPU/memory/disk; hang or flood I/O;
  or escape into the harness process.
- **Untrusted Track B patches.** Source diffs against a pinned Stockfish
  baseline that may try to smuggle in NNUE/book/tablebase payloads, network
  or process syscalls, harness fingerprinting, or binary artifacts.

A submission is assumed actively hostile, not merely buggy.

## Assets (what we protect)

1. **Evaluator source** — `bench/ceb/`. A submission that can import or read
   it can fingerprint opponents, scoring, and pack layout.
2. **Opponent pool** — `bench/ceb/match/opponents.py` and the engines it
   defines.
3. **Hidden eval packs** — private FENs, perft positions, and opening
   suites mounted by the operator (`--eval-pack` / `CEB_PRIVATE_EVAL_DIR`).
   Leaking these invalidates the benchmark.
4. **Private artifacts** — full round/match reports, game movetext, gate
   reports against hidden data (start FENs, move lists, host paths).
5. **The host** — the operator's machine, its filesystem, and credentials.

## Engine jail (the primary control)

The jail confines **only the untrusted engine**, not the evaluator. The
evaluator stays trusted on the host: it reads the hidden pack host-side and
drives the jailed engine over UCI. Code: `bench/ceb/jail/docker_engine.py`
and `engine_jail.py`; image `infra/docker/engine_jail.Dockerfile`, built by
`scripts/build_jail_image.sh`, tag `chess-en-bench-jail:0.3`.

Enforcement — the exact `docker run` flags emitted by `_base_argv` /
`build_engine_argv` in `docker_engine.py`:

- `--network none` — no egress at all.
- `--read-only` root filesystem + `--tmpfs /tmp` — immutable container.
- `--cpus 1`, `--memory 1g`, `--pids-limit 128` (`DEFAULT_LIMITS`).
- `--security-opt no-new-privileges`.
- `--user <host-uid>:<host-gid>` — never root in the container (POSIX).
- `-i` — UCI flows over the container's stdin/stdout.
- `-v <workspace>:/submission:ro` — the **only** mount, read-only. There is
  **no repository mount, no eval-pack mount, no opponent mount, no other-runs
  mount.** The engine sees nothing but its own workspace.
- `-w /submission`, and the engine is launched as `/submission/<engine_name>`.

Input validation (`validated_workspace`, `build_engine_argv`):

- A resolved workspace path containing `:` or a newline (the `-v` field
  separators) is rejected with `DockerJailError` — paths cannot smuggle extra
  mount options.
- An `engine_name` containing `/`, or equal to `""`/`.`/`..`, is rejected.

Lifecycle: containers run with `--rm`; `cleanup_containers()` force-kills any
stragglers (a hostile engine that ignores stdin EOF) via `docker kill`.

`build.sh` runs in the same jail with the workspace mounted **writable** (so
`./engine` can be produced) but still `--network none`
(`build_build_argv`). Missing Docker or a missing image raises an actionable
`EngineJailError` pointing at `scripts/build_jail_image.sh` — never a silent
host fallback.

### No `ceb` inside the jail image

The jail image is deliberately minimal: a Python runtime and bash, and
**nothing of the benchmark**. The `ceb` package is intentionally NOT installed
(`engine_jail.Dockerfile`), so even a jailed engine that executes Python
cannot `import ceb` to read evaluator code, opponents, or pack-resolution
logic. This is defense in depth on top of the absent mounts.

### Hidden packs combine safely with the jail

The private pack is read **host-side** by the evaluator. Positions reach the
jailed engine only as individual `position fen ...` UCI lines written to the
container's stdin. The pack directory is never mounted. Therefore
`--eval-pack` works *with* `--engine-jail docker` — unlike the legacy
`--sandbox docker`, which still rejects `--eval-pack` and runs private-pack
evaluations on the host.

## Artifact visibility (preventing leaks in output)

`bench/ceb/storage/artifacts.py` gives every artifact directory an
`artifacts_manifest.json`. `public_artifacts()` returns only files explicitly
marked `public` — **deny by default**: unknown or unlisted files are treated
as non-public.

For a round (`round_runner.py`):

- **Public:** `feedback.json`; `report.public.json` (schema
  `ceb.round.report.public/v1`, `verified:false`). For a private pack it omits
  host/workspace paths and sets `opening_coverage.opening_ids` to `null`;
  opening ids are emitted only for fully-public packs.
- **Private (operator-only):** `report.json` (full report with host paths and
  hidden opening ids), `match_vs_*.json`, `games_vs_*.txt`, `gate_report.json`.

The hosted worker re-derives visibility from the manifest when registering
artifacts in the DB and falls back to **private** for anything unlisted
(`worker.py::_register_artifacts`). The API then serves only DB-`public`
artifacts.

## Sanitized errors (preventing leaks in error paths)

`bench/ceb/sanitize.py`: `SanitizedError(public_message, private_message)`
carries two messages. `sanitize_exception()` returns the public text, or for
unknown exception types the fixed string `"internal error (<Type>); details
withheld — operators can rerun with CEB_DEBUG=1"` — because an arbitrary
exception message (e.g. a `ValueError` from FEN parsing) may embed a hidden
position.

`load_openings_jsonl(path, hidden=False)` and the eval-pack loaders take a
`hidden=` flag. Hidden errors quote only the file **basename** plus the row id
and the literal `"content withheld"` — never FENs, move sequences, or full
paths. Public data may be quoted in full.

CLI `main()` (`cli.py`) catches everything, prints a sanitized one-liner, and
returns nonzero (`3` for an unknown exception); it re-raises full tracebacks
only when `CEB_DEBUG=1`.

## Scanners (defense-in-depth tripwire)

The static scanners are a tripwire, not a proof system; hosted evaluation
combines them with the engine jail.

- **Track A** (`scan/static_scan.py`, `ceb scan workspace`): flags external
  chess libs / python-chess, external engines (stockfish/lc0/etc.), network
  use (socket/requests/urllib/http.client/aiohttp/httpx), process spawning
  (subprocess/os.system/os.popen/os.exec*), harness fingerprinting
  (`bench/ceb`, `CEB_*`, `eval_packs`, private paths,
  `ceb.match.opponents`), oversized files (>2 MB), book/tablebase/`.nnue`
  extensions, binary artifacts, and symlink escapes.
- **Track B** (`scan/track_b_scan.py`, `ceb scan track-b`): the diff
  whitelist plus binary/NNUE/book payloads, fingerprinting, network/process
  syscalls introduced into source, tablebase probing, and symlinks.

Both return `passed` plus `findings` with severity `fail`/`warn`.

## Process-level guarantees (always, every mode)

Independent of the jail, all engine I/O goes through
`bench/ceb/uci/client.py::UCIClient`: argv-only spawning (a string command
raises `TypeError`; no `shell=True`), a deadline on every read
(`EngineTimeout`/`EngineCrashed`), bounded stdout intake (queue capped at
10,000 lines, each truncated to 8,192 chars), `stderr` discarded, and
process-group teardown (`quit` → SIGTERM → SIGKILL on POSIX). See
[security.md](security.md) for the full list and its limits (notably:
`send()` writes are not deadline-protected).

## Verified results only from the official worker

Only the hosted worker (`bench/ceb/hosted/worker.py` →
`official_eval.py::run_official_eval`) produces `verified:true` results. It
runs, in order: static scan → strict gate vs the private pack →
`official_round` or `final_eval` with the private pack and optional engine
jail → public/private artifact split → reproducibility metadata + signing →
verified result. It **refuses to verify** (writes nothing verified) when there
is no private eval pack, the scan fails, or the strict gate fails. Submissions
are snapshotted (symlinks rejected, `submissions.py`) and tree-hashed; the
worker evaluates the snapshot, never the live workspace. The hosted
leaderboard (`db.verified_leaderboard`) is verified-only; quick rounds never
appear. Every self-reported local round is `verified:false`.

## Non-goals / NOT yet enforced (v0.3 honest limits)

- **Host execution is still the default.** `--engine-jail none` (and
  `--sandbox none`) run submissions as ordinary child processes of your user,
  with no filesystem/network/resource isolation. Nothing *forces*
  `--engine-jail docker`; the operator must choose it. The hosted worker
  passes whatever jail mode the operator configures.
- **Symmetric signing only (MVP).** Result signing is HMAC-SHA256 keyed by
  `CEB_SIGNING_KEY` (`hosted/signing.py`). Only key-holders can verify; this
  is authenticity *to the operator*, NOT public-key attestation. With no key,
  results are written `signature.status = "unsigned"` with an explicit "NO
  cryptographic authenticity" note, and `verify_result` returns
  `(False, "unsigned ...")`. Asymmetric attestation is future work.
- **Single-node MVP.** The hosted pipeline is SQLite + a local object dir
  (`<db>_store/`) with a single-worker `run-once` loop. No multi-tenant
  isolation, no distributed queue, no per-tenant resource accounting.
- **No seccomp/AppArmor profile beyond Docker's defaults**, and no user
  namespace remapping. The jail relies on Docker's default profile plus the
  flags above.
- **fastchess folds faults.** The optional fastchess adapter
  (`match/fastchess_runner.py`) does not attribute per-engine faults — it
  folds them into game results. The internal Python runner is the default and
  the **trusted reference**; fastchess is an opt-in throughput backend.
- **Track B CLI runs are diagnostic.** `ceb track-b official run` writes
  `verified:false`. Real pinned-Stockfish builds with identical compiler
  flags plus a `bench` sanity check are operator steps, not enforced in code.
- **No disk quota** on writable paths (the jailed build's `/submission`, the
  host `runs/`, the hosted object store).

## Checklist → enforcement → proof

Each row maps a defended property to the code that enforces it and the test
that proves it.

| Property | Enforced in | Proven by |
| --- | --- | --- |
| Engine jail mounts only the workspace, read-only; no repo/pack/opponent mount | `jail/docker_engine.py::build_engine_argv` | `tests/test_engine_jail.py::test_jail_argv_mounts_only_the_workspace` |
| Jail flags: `--network none`, `--read-only`, tmpfs, cpu/mem/pids caps, no-new-privileges, non-root, `-i` | `jail/docker_engine.py::_base_argv` | `tests/test_engine_jail.py::test_jail_argv_mounts_only_the_workspace` |
| Hidden pack is never mounted into the jail | `jail/engine_jail.py` (host-side reads); `docker_engine.py` (mount list) | `tests/test_engine_jail.py::test_eval_pack_combines_with_jail_without_mounting_it` |
| Build runs writable but offline | `jail/docker_engine.py::build_build_argv` | `tests/test_engine_jail.py::test_jail_build_argv_is_writable_but_offline` |
| Workspace path `:`/newline rejected; bad engine name rejected | `jail/docker_engine.py::validated_workspace`, `build_engine_argv` | `tests/test_engine_jail.py::test_workspace_validation` |
| Unknown jail mode rejected; missing Docker is actionable | `jail/engine_jail.py::_check_mode`, `docker_engine.py::ensure_ready` | `tests/test_engine_jail.py::test_engine_command_modes`, `test_missing_docker_is_actionable` |
| Straggler jail containers are reaped | `jail/docker_engine.py::cleanup_containers` | `tests/test_engine_jail.py::test_cleanup_kills_recorded_containers` |
| Jailed engine actually plays UCI (integration, opt-in) | `jail/*` + `uci/client.py` | `tests/test_engine_jail.py::test_jailed_engine_plays_over_uci` (skipped without `CEB_DOCKER_TESTS=1`) |
| Visibility manifest, deny-by-default | `storage/artifacts.py::public_artifacts`, `visibility_of` | `tests/test_artifact_visibility.py::test_manifest_tracks_visibility` |
| Round artifacts get the right public/private split | `rounds/round_runner.py` | `tests/test_artifact_visibility.py::test_round_artifacts_have_correct_visibility` |
| No hidden secret leaks into any public artifact | `rounds/round_runner.py::make_public_report` | `tests/test_artifact_visibility.py::test_public_artifacts_leak_scan` |
| Public report withholds host paths and hidden opening ids | `rounds/round_runner.py::make_public_report` | `tests/test_artifact_visibility.py::test_public_report_shape` |
| Hidden opening errors withhold board/moves; quote row id + basename | `sanitize.py`, `match/openings.py`, eval-pack loaders | `tests/test_sanitization.py::test_hidden_opening_illegal_move_does_not_leak_board`, `test_hidden_suite_file_errors_use_basename` |
| Unknown exceptions withheld; CLI returns sanitized one-liner, rc 3 | `sanitize.py::sanitize_exception`, `cli.py::main` | `tests/test_sanitization.py::test_cli_unknown_exception_is_withheld`, `test_cli_returns_sanitized_error_not_traceback` |
| Track A scanner flags cheats (libs/engines/network/spawn/fingerprint/binary/symlink/oversize) | `scan/static_scan.py` | `tests/test_scan.py::test_python_chess_import_fails`, `test_stockfish_invocation_fails`, `test_network_usage_fails`, `test_harness_fingerprinting_fails`, `test_symlink_escape_fails`, `test_book_extension_and_oversize_fail` |
| Track B scanner flags forbidden diffs, fingerprinting, symlinks | `scan/track_b_scan.py` | `tests/test_scan.py::test_track_b_forbidden_change_fails`, `test_track_b_fingerprinting_and_symlink_fail` |
| Only the worker produces verified results; refuses without pack / on scan fail / on gate fail | `hosted/worker.py`, `hosted/official_eval.py` | `tests/test_hosted.py::test_worker_produces_verified_result`, `test_worker_refuses_without_eval_pack`, `test_worker_refuses_when_scan_fails`, `test_worker_refuses_when_strict_gate_fails` |
| Submissions are snapshotted; symlinks rejected | `hosted/submissions.py::snapshot_workspace` | `tests/test_hosted.py::test_snapshot_rejects_symlinks` |
| Hosted leaderboard is verified-only; self-reported never verified | `hosted/db.py::verified_leaderboard` | `tests/test_hosted.py::test_hosted_leaderboard_is_verified_only`, `test_self_reported_rounds_never_appear_verified` |
| API serves only public artifacts; path traversal rejected | `api/main.py::hosted_artifact` | `tests/test_hosted.py::test_api_private_artifact_not_served`, `test_api_path_traversal_rejected` |
| API admin POSTs gated by token (503 unset / 403 wrong) | `api/main.py::_require_admin` | `tests/test_hosted.py::test_api_admin_endpoints_gated` |
| Signing: roundtrip, tamper detection, wrong key, unsigned-never-authentic | `hosted/signing.py` | `tests/test_signing.py::test_sign_and_verify_roundtrip`, `test_tampered_result_fails_verification`, `test_wrong_key_fails_verification`, `test_unsigned_mode_is_explicit_and_never_authentic` |
| Reproducibility metadata is complete; eval-pack hash is content-bound | `hosted/metadata.py::build_metadata`, `hash_directory` | `tests/test_signing.py::test_metadata_required_keys`, `test_eval_pack_hash_changes_with_contents` |
| Legacy `--sandbox docker` stays locked down and rejects nesting | `sandbox/docker_runner.py` | `tests/test_sandbox_docker.py::test_gate_argv_is_locked_down`, `test_recursion_guard` |
| UCIClient process-level safety (argv-only, timeouts, bounded intake) | `uci/client.py` | `tests/test_uci_client.py` |

Policy-level rules for submissions (no network, no reading harness internals)
and their consequences are normative in `specs/forbidden_behaviors.md`.
