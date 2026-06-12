# chess_en_bench

A benchmark platform for LLM coding agents that **build chess engines from
scratch** (Track A) or **optimize Stockfish's search** (Track B) under
controlled, reproducible conditions.

v0.1 is a fully local MVP: the public gate, Track A quick rounds, the internal
match runner, scoring, the CLI, and the API/dashboard all run on your machine
with no hidden data and no external chess libraries in the core.

## Quickstart

```bash
git clone https://github.com/junyeopYim/chess_en_bench.git
cd chess_en_bench
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,server]"

ceb doctor                       # environment diagnosis
pytest -q                        # 69 tests: FEN, movegen/perft, UCI, gate, scoring, CLI
```

Run the public gate and a quick round against the bundled example engine:

```bash
ceb gate run  --track A --workspace examples/submissions/minimal_uci_engine_python
ceb round run --track A --workspace examples/submissions/minimal_uci_engine_python --round 1 --quick
ceb leaderboard compute --track A --results runs
ceb server start --host 127.0.0.1 --port 8000   # dashboard at http://127.0.0.1:8000/
```

## The two tracks

**Track A — from-scratch engine.** The evaluated agent receives a public spec
([specs/uci_minimal.md](specs/uci_minimal.md)), a public correctness gate, and
example FEN/perft data ([tracks/a_from_scratch/public/](tracks/a_from_scratch/public/)).
It must produce a self-contained UCI engine. The gate may be run **unlimited**
times; official rounds are budgeted (3 per run). Rounds play the engine against
a ladder of benchmark-owned opponents (BenchRandom … BenchAlphaBeta3) and score
it with an Elo-style ladder rating minus fault penalties. See
[docs/track_a_from_scratch.md](docs/track_a_from_scratch.md).

**Track B — Stockfish search optimization.** The agent edits only
search-related files of a **pinned** baseline (Stockfish 18, tag `sf_18`,
commit `cb3d4ee` — never a moving branch) under a diff whitelist, and is scored
by candidate-vs-baseline delta Elo. v0.1 ships the pin, the whitelist checker
(`ceb track-b check-diff`), status tooling, and the scoring model; automated
candidate-vs-baseline match orchestration is planned. See
[docs/track_b_stockfish_optimization.md](docs/track_b_stockfish_optimization.md).

```bash
bash scripts/setup_stockfish.sh   # optional: fetch the pinned baseline (GPLv3, gitignored)
ceb track-b status
```

## How an evaluation runs

1. `ceb workspace prepare --track A --run-id myrun` — creates `runs/myrun/`.
2. The agent iterates: edit engine → `ceb gate run …` → read the JSON report →
   repeat. Gate attempts are free and unlimited.
3. When the gate passes, spend an official round:
   `ceb round run --track A --workspace … --round 1` (use `--quick` for a free
   smoke round). Each round writes `runs/<id>/round_N/report.json` plus
   sanitized, aggregate-only feedback.
4. The run's final score is its **best valid round**;
   `ceb leaderboard compute` ranks runs.

Details: [docs/benchmark_protocol.md](docs/benchmark_protocol.md) and
[docs/agent_protocol.md](docs/agent_protocol.md).

## Repository layout

| Path | Contents |
| --- | --- |
| `bench/ceb/` | Python package: chess oracle, UCI client, gate, match runner, scoring, rounds, Track B tools, API, CLI |
| `tracks/` | Track configs, public data, prompts, scoring/penalty tables |
| `specs/` | Normative contracts (UCI subset, perft extension, submission, feedback, forbidden behaviors) |
| `docs/` | Protocol, scoring, security, reproducibility, licensing docs |
| `examples/submissions/` | A minimal passing engine and intentionally broken engines |
| `tests/` | pytest suite (canonical perft counts included) |
| `runs/`, `artifacts/` | Local outputs (gitignored) |

## Design notes

- The **oracle** (`bench/ceb/chess/`) is dependency-free and validated against
  canonical perft counts; it adjudicates every move in every game.
- Submitted engines are **untrusted**: argv-only spawning, timeouts on every
  read, bounded output intake, process-group kill. Run unknown submissions in
  a disposable environment; see [docs/security.md](docs/security.md).
- Everything machine-readable uses versioned JSON schemas
  (`ceb.gate.report/v1`, `ceb.round.feedback/v1`, …).

License: MIT (see [LICENSE](LICENSE)); Stockfish is GPLv3 and is **not**
distributed with this repository (see [NOTICE](NOTICE)).
