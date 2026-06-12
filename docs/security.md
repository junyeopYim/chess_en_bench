# Security model (v0.1)

chess_en_bench executes code it did not write: submitted engines (and their
`build.sh`) are produced by the LLM agents under evaluation. Treat every
submission as untrusted. This document states the threat model, what v0.1
actually enforces in code, what it does not, and how operators should run it.

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

v0.1 mitigates the first four classes in code. The last three are **not**
isolated in v0.1 and are handled by policy (`specs/forbidden_behaviors.md`)
plus operator-level sandboxing.

## Enforced in v0.1

All engine process handling goes through `bench/ceb/uci/client.py`
(`UCIClient`). Concrete guarantees, verifiable in that file:

- **argv-only spawning, never a shell.** `UCIClient(command)` raises
  `TypeError` if `command` is a string; processes start via
  `subprocess.Popen(argv_list)` with no `shell=True` anywhere. No submission
  string is ever interpolated into a shell command.
- **Every read has a timeout.** `read_line`, `expect`, `handshake`, `sync`,
  `go_movetime`, and `go_perft` all take deadlines and raise `EngineTimeout`
  / `EngineCrashed` instead of blocking forever.
- **Bounded stdout intake.** A reader thread feeds a queue capped at 10,000
  lines (`_QUEUE_MAX_LINES`), each truncated to 8,192 characters
  (`_MAX_LINE_CHARS`). A flooding engine blocks on its own pipe
  (backpressure); it cannot grow harness memory without bound.
- **stderr is discarded** (`stderr=subprocess.DEVNULL`), so engines cannot
  flood or spoof the harness through that channel.
- **Process-group teardown.** On POSIX the engine starts in its own session
  (`start_new_session=True`). `close()` sends `quit`, waits briefly, then
  escalates SIGTERM → SIGKILL to the whole process group, so children the
  engine spawned are killed too.
- **build.sh runs bounded.** The gate (`bench/ceb/gate/gate_runner.py`)
  invokes it as `["bash", build.sh]` with `cwd` set to the workspace, output
  captured, and a 120-second timeout — but on the host, with your
  privileges (see below).
- **Every move is oracle-validated.** The internal match runner
  (`bench/ceb/match/internal_runner.py`) checks each move against
  `bench/ceb/chess/`; illegal output is recorded as a fault, never replayed
  blindly.

## NOT enforced in v0.1

Be explicit about the gaps. The harness runs submissions as ordinary child
processes of your user on your machine. There is **no**:

- filesystem isolation — an engine (or `build.sh`) can read and write
  anything your user can, including `bench/ceb/`, `runs/`, and `$HOME`;
- network isolation — outbound connections are not blocked or detected;
- CPU, memory, or disk quota — only wall-clock timeouts exist;
- privilege separation — no dedicated user, namespaces, or seccomp.

Container sandboxing is planned, not implemented. Until then, a pattern like
this is the recommended way to wrap an evaluation host:

```sh
docker run --rm \
  --network none \
  --memory 2g --cpus 2 --pids-limit 256 \
  --read-only --tmpfs /tmp \
  -v "$PWD":/bench:ro \
  -v "$PWD/runs":/bench/runs \
  -w /bench \
  python:3.13-slim \
  bash -c "pip install -e . && ceb gate run --track A --workspace runs/demo/workspace"
```

Key properties: `--network none` (no egress), read-only repo mount with only
`runs/` writable, hard memory/CPU/pid limits, and `--rm` so nothing persists.
Adapt the image to include a C/C++ toolchain if submissions compile native
engines.

## Operator guidance

- Run untrusted submissions **only in disposable environments**: a container
  as above, a throwaway VM, or at minimum a dedicated low-privilege user.
  Never on a machine holding credentials you care about.
- Never run the harness as root.
- Skim `build.sh` and the workspace before `ceb gate run`; it executes with
  your privileges in v0.1.
- After a suspicious run, discard the environment rather than cleaning it.
- Keep result directories (`runs/`, `artifacts/`) on a path the engine had
  no reason to touch, and treat them as data, not code.
- Policy-level rules for submissions (no network, no reading harness
  internals, etc.) and their consequences are normative in
  `specs/forbidden_behaviors.md`.
