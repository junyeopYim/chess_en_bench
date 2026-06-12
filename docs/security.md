# Security model

chess_en_bench executes code it did not write: submitted engines (and their
`build.sh`) are produced by the LLM agents under evaluation. Treat every
submission as untrusted. This document states the threat model, what the
harness actually enforces in code, what it does not, and how operators
should run it.

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
last three are isolated only when you run with `--sandbox docker`; with the
default `--sandbox none` they remain policy-only (`specs/forbidden_behaviors.md`).

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
  invokes it as `["bash", build.sh]` with output captured and a 120-second
  timeout.
- **Every move is oracle-validated** against `bench/ceb/chess/`; illegal
  output is recorded as a fault, never replayed blindly.
- **Gate failure details quote row ids only** — bestmove/perft check
  messages never include FENs, so hidden eval-pack positions cannot leak
  through reports or agent feedback.

## Docker sandbox (`--sandbox docker`)

`ceb gate run --sandbox docker` and `ceb round run --sandbox docker`
re-invoke `ceb` inside a locked-down container
(`bench/ceb/sandbox/docker_runner.py`, image
`chess-en-bench-evaluator:0.2` from `infra/docker/evaluator.Dockerfile`).
Build the image once:

```sh
bash scripts/build_evaluator_image.sh
ceb gate run --track A --workspace runs/demo/workspace --sandbox docker
ceb round run --track A --workspace runs/demo/workspace --round 1 --quick --sandbox docker
```

The runner constructs the `docker run` argv itself; exact enforcement:

- `--network none` — no egress at all.
- `--read-only` rootfs plus `--tmpfs /tmp` — the container filesystem is
  immutable.
- `--cpus 2 --memory 2g --pids-limit 256` — resource caps (defaults in
  `DEFAULT_LIMITS`).
- `--security-opt no-new-privileges` and `--user <host-uid>:<host-gid>` —
  no privilege escalation, never root in the container.
- The repo is mounted **read-only** at `/bench` (`CEB_ROOT=/bench`); only
  `runs/` and the submission workspace (at `/sandbox/workspace`) are
  writable. An engine cannot modify `bench/ceb/` or opponents.
- argv lists everywhere — untrusted paths are never shell-interpolated.
- Mount-path validation: a resolved host path containing `:` or a newline
  (the `-v` field separator) is rejected with `SandboxError`, so paths
  cannot smuggle extra mount options.
- `CEB_INSIDE_SANDBOX=1` recursion guard — a nested `--sandbox docker`
  refuses to start a container inside the container.
- Missing docker or a missing image fails with an actionable `SandboxError`
  (install Docker / run the build script), never a silent host fallback.

## NOT enforced

- **Host execution is still the default.** `--sandbox none` runs submissions
  as ordinary child processes of your user — no filesystem, network, or
  resource isolation. Nothing forces you to pass `--sandbox docker`.
- **No seccomp/AppArmor profile beyond Docker's defaults**, and no user
  namespace remapping.
- **`--eval-pack` is not supported with `--sandbox docker`** (the CLI
  rejects the combination); private-pack evaluations currently run on the
  host.
- **Engine stdin writes are unbounded.** `UCIClient.send()` has no timeout;
  an engine that never drains stdin can block a harness write on a full pipe
  (reads are deadline-protected, writes are not).
- **No disk quota** on the writable mounts (`runs/` and the workspace).

## Operator guidance

- **Use `--sandbox docker` for any submission you did not write.** Build the
  evaluator image first; keep `--sandbox none` for trusted local debugging.
- If you must run on the host, use a disposable environment (throwaway VM or
  dedicated low-privilege user), never a machine holding credentials.
- Never run the harness as root; the sandbox also refuses root inside the
  container by mapping your uid:gid.
- Skim `build.sh` and the workspace before a host-mode `ceb gate run`; it
  executes with your privileges there.
- After a suspicious run, discard the environment rather than cleaning it.
- Treat `runs/` and `artifacts/` as data, not code.
- Policy-level rules for submissions (no network, no reading harness
  internals, etc.) and their consequences are normative in
  `specs/forbidden_behaviors.md`.
