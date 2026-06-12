# chess_en_bench — Overview

chess_en_bench is a benchmark platform for LLM coding agents that build or
optimize chess engines. An agent gets a workspace, explicit instructions, and
public test data; the harness verifies the engine through a public correctness
gate, plays seeded matches against a fixed opponent pool, and turns the results
into Elo-based scores and a leaderboard. v0.1 is a local MVP: everything runs
on one machine, there is no hidden evaluation data, and `tracks/*/private/`
directories are documented placeholders only.

## The two tracks

**Track A — from-scratch engine** (`tracks/a_from_scratch/`). The agent builds
a UCI chess engine from nothing. The workspace must contain an executable
`engine` (or a `build.sh` that produces one). Unlimited public gate attempts
precede a budget of 3 official rounds per run; each official round plays the
candidate against six bundled opponents (BenchRandom 400 up to BenchAlphaBeta3
1400 nominal Elo) and scores it as a ladder rating minus fault penalties.

**Track B — Stockfish search optimization** (`tracks/b_stockfish_opt/`). The
agent may modify only search-related files of a pinned Stockfish baseline
(Stockfish 18, tag `sf_18`, commit `cb3d4ee` — never a moving branch, see
`stockfish.lock`). Scoring is delta Elo of candidate vs baseline with a
confidence interval (`ceb.score.track_b/v1`). Implemented in v0.1: the lock
file, allowed/forbidden path lists, the diff whitelist checker
(`ceb track-b check-diff`), the status command (`ceb track-b status`),
`scripts/setup_stockfish.sh`, and the delta-Elo scoring module. **Not**
implemented in v0.1: automated candidate-vs-baseline match orchestration —
you run the matches yourself and feed W/D/L into the scoring module.

## Design principles

- **Explicit instructions.** Each track ships a `prompt.md`; `ceb workspace
  prepare` copies it into the run as `instructions.md`. No implicit rules.
- **Structured, machine-readable outputs.** Every artifact is versioned JSON:
  `ceb.run.state/v1`, `ceb.gate.report/v1`, `ceb.round.report/v1`,
  `ceb.round.feedback/v1`, `ceb.score.track_a/v1`, `ceb.score.track_b/v1`,
  `ceb.leaderboard/v1`. Agents can parse results instead of scraping text.
- **Public examples, no hidden data.** Gate FENs, perft counts, and openings
  live under `tracks/*/public/`; working and broken example submissions live
  under `examples/submissions/`.
- **Iterative gate -> round loop.** Gate attempts are unlimited and free, so an
  agent can fix correctness cheaply, then spend its limited official rounds on
  strength evaluation. Quick rounds (`--quick`) give free strength smoke tests.
- **Sanitized feedback.** Round feedback (`ceb.round.feedback/v1`) is
  aggregate-only: per-opponent W/D/L and score rates, fault counts, scores,
  and generic advice. No move logs, no evaluation internals.
- **Reproducible run metadata.** Each run persists `state.json` (budget, gate
  status, round trajectory with timestamps); match games are seeded
  deterministically per round (`base_seed = 1000 * round_number`), colors
  alternate, and configs are plain files under `tracks/`.
- **Untrusted-code handling.** Engines are spawned argv-only (never
  `shell=True`), all reads have timeouts, stdout is bounded, and processes are
  terminated by process-group SIGTERM/SIGKILL. Docker sandboxing is
  recommended in the docs but not implemented in v0.1.

## Repository layout

| Path | Contents |
|---|---|
| `bench/ceb/` | Python package: `cli.py`, `gate/`, `match/`, `rounds/`, `scoring/`, `chess/` (internal oracle), `uci/`, `track_b/`, `api/` |
| `tracks/a_from_scratch/` | Track A prompt, `track.yaml`, `scoring.yaml`, `public/` (FENs, perft, openings, gate config) |
| `tracks/b_stockfish_opt/` | Track B prompt, `stockfish.lock`, path lists, `patch_policy.yaml`, `public/` |
| `specs/` | Protocol and contract specs (submission contract, UCI perft extension) |
| `docs/` | This documentation |
| `scripts/` | `setup_dev.sh`, `setup_stockfish.sh`, `run_public_gate.sh` |
| `examples/submissions/` | Minimal working Python UCI engine + broken-engine examples |
| `web/static/` | Dashboard frontend served by `ceb server start` |
| `tests/` | pytest suite |
| `runs/` | Run artifacts: `runs/<run_id>/...`, ad-hoc gate reports in `runs/_gate/` |
| `artifacts/` | Miscellaneous build/eval artifacts |

## Quickstart (5 commands)

```bash
bash scripts/setup_dev.sh && . .venv/bin/activate   # venv + pip install -e ".[dev,server]"

ceb doctor                                          # check environment
ceb workspace prepare --track A --run-id demo       # creates runs/demo/workspace
ceb gate run --track A --workspace runs/demo/workspace        # unlimited attempts
ceb round run --track A --workspace runs/demo/workspace --round 1 --quick  # free smoke round
ceb leaderboard compute --track A --results runs    # rank runs by best scored round
```

The CLI is installed as the console script `ceb` and is also runnable as
`python -m ceb.cli`. Core gate/match/scoring need only the Python standard
library; FastAPI/uvicorn are optional extras for `ceb server start`. To try
the loop without writing an engine first, point `--workspace` at
`examples/submissions/minimal_uci_engine_python` (see the `gate` and `round`
targets in the `Makefile`).

For the full run lifecycle and budget rules, see
`docs/benchmark_protocol.md`.
