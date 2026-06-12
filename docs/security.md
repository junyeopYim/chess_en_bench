# Operator security guide

chess_en_bench executes code it did not write: submitted engines (and their
`build.sh`) are produced by the LLM agents under evaluation. Treat every
submission as untrusted. This document is the operator-facing guide: how to
run the harness safely and what each isolation mode does. For the formal
trust model — assets, the full enforcement list, and v0.3's explicit
non-goals — see [SECURITY_MODEL.md](SECURITY_MODEL.md).

The recommended isolation for any submission you did not write is the
**engine jail** (`--engine-jail docker`), which confines only the untrusted
engine. The legacy `--sandbox docker` (whole harness in a container) still
exists but does not support hidden eval packs; see below.

## Threat model

A submitted engine is an arbitrary native or interpreted program. Hostile or
simply buggy submissions may try to:

- run shell commands or escape into the harness process,
- hang forever, or stall single reads, to block evaluation,
- flood stdout/stderr to exhaust harness memory,
- leave orphaned child processes behind,
- read or modify benchmark internals, opponents, results, or the filesystem,
- use the network (download a stronger engine, query an online engine, exfiltrate data),
- exhaust CPU, memory, or disk.

The first four classes are mitigated at the process level on every run. The
last three are isolated when you run the untrusted engine with
`--engine-jail docker`; with the default `--engine-jail none` (host
execution) they remain policy-only (`specs/forbidden_behaviors.md`).

## Enforced at the process level (every run)

All engine process handling goes through `bench/ceb/uci/client.py`
(`UCIClient`). Concrete guarantees, verifiable in that file:

- **argv-only spawning, never a shell.** `UCIClient(command)` raises
  `TypeError` if `command` is a string; processes start via
  `subprocess.Popen(argv_list)` with no `shell=True` anywhere.
- **Every read has a timeout.** `read_line`, `expect`, `handshake`, `sync`,
  `go_movetime`, and `go_perft` all take deadlines and raise `EngineTimeout`
  / `EngineCrashed` instead of blocking forever.
- **Bounded stdout intake.** A reader thread feeds a queue capped at 10,000
  lines (`_QUEUE_MAX_LINES`), each truncated to 8,192 characters
  (`_MAX_LINE_CHARS`). A flooding engine blocks on its own pipe.
- **stderr is discarded** (`stderr=subprocess.DEVNULL`).
- **Process-group teardown.** On POSIX the engine starts in its own session;
  `close()` escalates `quit` → SIGTERM → SIGKILL to the whole process group.
- **build.sh runs bounded.** The gate (`bench/ceb/gate/gate_runner.py`)
  invokes it with output captured and a 120-second timeout. Under
  `--engine-jail none` it runs as `["bash", build.sh]` on the host; under
  `--engine-jail docker` it runs inside the jail (offline, workspace
  writable).
- **Every move is oracle-validated** against `bench/ceb/chess/`; illegal
  output is recorded as a fault, never replayed blindly.
- **Gate failure details quote row ids only** — bestmove/perft check
  messages never include FENs, so hidden eval-pack positions cannot leak
  through reports or agent feedback.

## Engine jail (`--engine-jail docker`) — recommended

This is the path official hosted evaluation uses, and the one to use for any
submission you did not write. It confines **only the untrusted engine** in a
locked-down container while the evaluator stays trusted on the host. The
evaluator reads the hidden pack host-side and drives the jailed engine over
UCI, so `--engine-jail docker` works **with** `--eval-pack`.

`ceb gate run`, `ceb round run`, and `ceb track-b round run` all accept
`--engine-jail none|docker` (default `none`). Build the image once
(`infra/docker/engine_jail.Dockerfile`, tag `chess-en-bench-jail:0.3`):

```sh
bash scripts/build_jail_image.sh
ceb gate run --track A --workspace runs/demo/workspace --engine-jail docker
ceb round run --track A --workspace runs/demo/workspace --round 1 \
    --engine-jail docker --eval-pack /path/to/private/pack
```

Enforcement (`bench/ceb/jail/docker_engine.py`):

- `--network none` — no egress at all.
- `--read-only` rootfs plus `--tmpfs /tmp` — immutable container filesystem.
- `--cpus 1 --memory 1g --pids-limit 128` — resource caps (`DEFAULT_LIMITS`).
- `--security-opt no-new-privileges` and `--user <host-uid>:<host-gid>` —
  no privilege escalation, never root in the container.
- The submission workspace is the **only** mount, read-only at `/submission`
  (`-v <workspace>:/submission:ro`). There is no repository mount, no
  eval-pack mount, and no opponent mount — the engine sees nothing else. The
  build step mounts the workspace writable (so `./engine` can be produced)
  but stays `--network none`.
- The jail image deliberately does **not** install the `ceb` package, so a
  jailed engine cannot import evaluator code even if it runs Python.
- argv lists everywhere; a resolved workspace path containing `:` or a
  newline (the `-v` field separator) is rejected, as is an engine name
  containing `/`.
- Missing Docker or a missing image fails with an actionable
  `EngineJailError` (install Docker / run `scripts/build_jail_image.sh`),
  never a silent host fallback.

For the full asset map, the no-`ceb`-in-image property, and the
checklist→test mapping, see [SECURITY_MODEL.md](SECURITY_MODEL.md).

## Legacy whole-harness sandbox (`--sandbox docker`)

`--sandbox docker` predates the engine jail: it re-invokes the entire `ceb`
harness inside one container (`bench/ceb/sandbox/docker_runner.py`, image
`chess-en-bench-evaluator:0.2`). It still applies `--network none`,
`--read-only` + `--tmpfs /tmp`, `--cpus 2 --memory 2g --pids-limit 256`,
`--security-opt no-new-privileges`, a non-root `--user`, the same `:`/newline
mount-path validation, and a `CEB_INSIDE_SANDBOX=1` recursion guard. The repo
is mounted read-only at `/bench`; only `runs/` and the workspace are writable.

Prefer the engine jail. The legacy sandbox **rejects `--eval-pack`** (the CLI
errors on the combination), so it cannot run hidden-pack evaluations — those
would run on the host. Official hosted evaluation uses `--engine-jail docker`,
not `--sandbox docker`.

## NOT enforced

- **Host execution is still the default.** `--engine-jail none` (and
  `--sandbox none`) run submissions as ordinary child processes of your user
  — no filesystem, network, or resource isolation. Nothing forces you to pass
  `--engine-jail docker`.
- **No seccomp/AppArmor profile beyond Docker's defaults**, and no user
  namespace remapping.
- **Engine stdin writes are unbounded.** `UCIClient.send()` has no timeout;
  an engine that never drains stdin can block a harness write on a full pipe
  (reads are deadline-protected, writes are not).
- **No disk quota** on writable paths (the jailed build's `/submission`,
  `runs/`, the hosted object store).

See [SECURITY_MODEL.md](SECURITY_MODEL.md) for the complete non-goals list
(symmetric-only signing, single-node hosted MVP, fastchess folding faults,
diagnostic Track B CLI runs).

## Operator guidance

- **Use `--engine-jail docker` for any submission you did not write.** Build
  the jail image first; keep `--engine-jail none` for trusted local
  debugging. It composes with `--eval-pack` for private-pack runs.
- If you must run on the host, use a disposable environment (throwaway VM or
  dedicated low-privilege user), never a machine holding credentials.
- Never run the harness as root; the jail also refuses root inside the
  container by mapping your uid:gid.
- Skim `build.sh` and the workspace before a host-mode (`--engine-jail none`)
  `ceb gate run`; it executes with your privileges there.
- After a suspicious run, discard the environment rather than cleaning it.
- Treat `runs/` and `artifacts/` as data, not code.
- Policy-level rules for submissions (no network, no reading harness
  internals, etc.) and their consequences are normative in
  `specs/forbidden_behaviors.md`.
