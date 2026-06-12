# chess_en_bench — Overview

chess_en_bench is a benchmark platform for LLM coding agents that build or
optimize chess engines. An agent gets a workspace, explicit instructions, and
public test data; the harness verifies the engine through a correctness gate,
plays seeded matches from a validated opening suite against a fixed opponent
pool, and turns the results into Elo-based scores and an official leaderboard.
v0.2 runs on one machine; evaluations can run inside a locked-down Docker
sandbox, and operators may mount a private eval pack — no hidden data is
shipped in this repository.

## The two tracks

**Track A — from-scratch engine** (`tracks/a_from_scratch/`). The agent builds
a UCI chess engine from nothing. The workspace must contain an executable
`engine` (or a `build.sh` that produces one). Unlimited public gate attempts
precede a budget of 3 official rounds per run. Every official round first
re-runs the **strict** gate (the `go perft` extension is mandatory there),
then plays the candidate against six bundled opponents (BenchRandom 400 up to
BenchAlphaBeta3 1400 nominal Elo) and scores it as a ladder rating minus
fault penalties. Optional Stockfish `UCI_Elo` anchor opponents can be enabled
in `scoring.yaml`; they are skipped gracefully when the binary is absent.

**Track B — Stockfish search optimization** (`tracks/b_stockfish_opt/`). The
agent may modify only search-related files of a pinned Stockfish baseline
(Stockfish 18, tag `sf_18`, commit `cb3d4ee` — never a moving branch, see
`stockfish.lock`). Scoring is delta Elo of candidate vs baseline with a
confidence interval (`ceb.score.track_b/v1`). `ceb track-b round run
--candidate-engine <X> --baseline-engine <Y>` automates the evaluation: diff
whitelist check (a violation aborts before any game), UCI handshake checks,
paired-opening alternating-color games with `Threads=1 Hash=16` sent to both
engines, then scoring and sanitized feedback. **Planned, not implemented:**
a fastchess/cutechess match-runner adapter.

## Design principles

- **Explicit instructions.** Each track ships a `prompt.md`; `ceb workspace
  prepare` copies it into the run as `instructions.md`. No implicit rules.
- **Structured, machine-readable outputs.** Every artifact is versioned JSON:
  `ceb.run.state/v1`, `ceb.gate.report/v1`, `ceb.round.report/v1`,
  `ceb.round.feedback/v1`, `ceb.score.track_a/v1`, `ceb.score.track_b/v1`,
  `ceb.track_b.round.report/v1`, `ceb.track_b.feedback/v1`,
  `ceb.leaderboard/v1`. Agents can parse results instead of scraping text.
- **Public data shipped, hidden data optional.** Gate FENs, perft counts, and
  the oracle-validated JSONL opening suite live under `tracks/*/public/`.
  Operators may mount a private eval pack (`--eval-pack <dir>`, or
  `CEB_PRIVATE_EVAL_DIR` for official rounds and the strict gate) that
  extends the public data; `examples/eval_packs/tiny_private/` documents the
  shape. Working and broken example submissions live under
  `examples/submissions/`.
- **Iterative gate -> round loop.** Gate attempts are unlimited and free.
  The standalone public gate and quick rounds (`--quick`) are non-strict
  smoke tests; official rounds always run the strict gate and spend budget.
- **Sanitized feedback.** Agent-facing `feedback.json` is aggregate-only:
  per-opponent W/D/L and score rates, fault counts, scores, generic advice.
  No FENs, no move logs, no opening ids — full detail stays in operator
  artifacts (`report.json`, `match_vs_*.json`).
- **Reproducible run metadata.** Each run persists `state.json`; games are
  seeded per round (`base_seed = 1000 * round_number`), colors alternate per
  opening pair, the suite is rotated across opponents, and round reports
  record `openings_used`, `strict_gate`, and the resolved `eval_pack`.
- **Untrusted-code handling.** Engines are spawned argv-only (never
  `shell=True`), reads have timeouts, stdout is bounded, processes die by
  process-group SIGTERM/SIGKILL. `--sandbox docker` additionally runs the
  gate or round inside a no-network, read-only, resource-capped container
  (`chess-en-bench-evaluator:0.2`) — recommended for untrusted submissions;
  the default stays `--sandbox none`.

## Repository layout

| Path | Contents |
|---|---|
| `bench/ceb/` | Python package: `cli.py`, `eval_pack.py`, `gate/`, `match/` (incl. `openings.py`), `rounds/`, `scoring/`, `sandbox/` (Docker runner), `chess/` (internal oracle), `uci/`, `track_b/`, `api/` |
| `tracks/a_from_scratch/` | Track A prompt, `track.yaml`, `scoring.yaml`, `public/` (FENs, perft, `openings_public.jsonl`, gate config) |
| `tracks/b_stockfish_opt/` | Track B prompt, `stockfish.lock`, path lists, `patch_policy.yaml`, `public/` (incl. `quick_openings.jsonl`) |
| `specs/` | Protocol and contract specs (submission contract, UCI perft extension) |
| `docs/` | This documentation |
| `scripts/` | `setup_dev.sh`, `setup_stockfish.sh`, `run_public_gate.sh`, `build_evaluator_image.sh` |
| `examples/` | `submissions/` (working + broken engines), `eval_packs/tiny_private/` (fake demo pack used by tests) |
| `infra/docker/` | `evaluator.Dockerfile` for the sandbox image |
| `.github/workflows/ci.yml` | CI: pytest, doctor, public + strict gate, quick-round smoke, leaderboard, API import on Python 3.10–3.12 (no Stockfish, no Docker build) |
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
ceb leaderboard compute --track A --results runs    # official rounds only
```

The CLI is installed as the console script `ceb` and is also runnable as
`python -m ceb.cli`. A prepared workspace at `runs/demo/workspace` infers run
id `demo`; `--run-id` always overrides. Add `--strict` to the gate to preview
the official-round check, and `--include-quick` to the leaderboard for a
diagnostic view (the output labels it as non-official). For untrusted code,
build the sandbox once (`bash scripts/build_evaluator_image.sh`) and run gate
or round with `--sandbox docker` (note: `--eval-pack` is not supported there).
Core gate/match/scoring need only the Python standard library;
FastAPI/uvicorn are optional extras for `ceb server start`. To try the loop
without writing an engine first, point `--workspace` at
`examples/submissions/minimal_uci_engine_python` (see the `gate` and `round`
targets in the `Makefile`).

For the full run lifecycle and budget rules, see
`docs/benchmark_protocol.md`.
