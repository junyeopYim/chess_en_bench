# chess_en_bench

A benchmark platform for LLM coding agents that **build chess engines from
scratch** (Track A) or **optimize Stockfish's search** (Track B) under
controlled, reproducible conditions.

v0.2 runs fully locally and adds the credibility layer on top of the v0.1
MVP: a **strict gate** (perft mandatory) for official rounds, **opening
suites** instead of startpos-only play, an **official leaderboard that
excludes quick rounds**, a **Docker sandbox** for untrusted submissions, an
operator-mounted **hidden eval pack interface** (no hidden data shipped), an
**automated Track B candidate-vs-baseline runner**, and **GitHub Actions CI**.

## Quickstart

```bash
git clone https://github.com/junyeopYim/chess_en_bench.git
cd chess_en_bench
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,server]"

ceb doctor                       # environment diagnosis
pytest -q                        # full suite: oracle perft, UCI, gate, openings, eval packs, sandbox, scoring, CLI
```

Run the public gate and a quick round against the bundled example engine:

```bash
ceb gate run  --track A --workspace examples/submissions/minimal_uci_engine_python
ceb gate run  --track A --workspace examples/submissions/minimal_uci_engine_python --strict
ceb round run --track A --workspace examples/submissions/minimal_uci_engine_python --round 1 --quick
ceb leaderboard compute --track A --results runs                 # official rounds only
ceb leaderboard compute --track A --results runs --include-quick # diagnostic view
ceb server start --host 127.0.0.1 --port 8000   # dashboard at http://127.0.0.1:8000/
```

For untrusted submissions, run evaluations inside the Docker sandbox
(`--network none`, read-only root, CPU/memory/pids limits, non-root):

```bash
bash scripts/build_evaluator_image.sh
ceb gate run  --track A --workspace <dir> --sandbox docker
ceb round run --track A --workspace <dir> --round 1 --quick --sandbox docker
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
by candidate-vs-baseline delta Elo. v0.2 adds the automated round runner:
diff check → handshake verification → paired-opening games (Threads=1,
fixed Hash) → delta-Elo report with confidence interval. See
[docs/track_b_stockfish_optimization.md](docs/track_b_stockfish_optimization.md).

```bash
bash scripts/setup_stockfish.sh   # optional: fetch the pinned baseline (GPLv3, gitignored)
ceb track-b status
ceb track-b round run --candidate-engine <path> --baseline-engine <path> \
    --baseline-src <tree> --candidate-src <tree>
```

## How an evaluation runs

1. `ceb workspace prepare --track A --run-id myrun` — creates `runs/myrun/`;
   `round run` on `runs/myrun/workspace` infers the run id automatically.
2. The agent iterates: edit engine → `ceb gate run …` → read the JSON report →
   repeat. Gate attempts are free and unlimited.
3. When the gate passes, spend an official round:
   `ceb round run --track A --workspace … --round 1` (use `--quick` for a free
   smoke round). Official rounds re-run the **strict** gate (perft mandatory),
   start games from the opening suite, and may consume an operator-mounted
   hidden eval pack (`--eval-pack` / `CEB_PRIVATE_EVAL_DIR`). Each round
   writes `runs/<id>/round_N/report.json` plus sanitized, aggregate-only
   feedback.
4. The run's final score is its **best valid official round**;
   `ceb leaderboard compute` ranks runs (quick rounds excluded by default).

Details: [docs/benchmark_protocol.md](docs/benchmark_protocol.md) and
[docs/agent_protocol.md](docs/agent_protocol.md).

## Repository layout

| Path | Contents |
| --- | --- |
| `bench/ceb/` | Python package: chess oracle, UCI client, gate, match runner, openings, eval packs, sandbox, scoring, rounds, Track B tools, API, CLI |
| `tracks/` | Track configs, public data (incl. `openings_public.jsonl`), prompts, scoring/penalty tables |
| `specs/` | Normative contracts (UCI subset, perft extension, submission, feedback, forbidden behaviors) |
| `docs/` | Protocol, scoring, security, reproducibility, licensing docs |
| `examples/submissions/` | A minimal passing engine and intentionally broken engines |
| `examples/eval_packs/tiny_private/` | Fake demo hidden-pack showing the operator interface |
| `infra/docker/` | Evaluator sandbox image (`scripts/build_evaluator_image.sh`) |
| `tests/` | pytest suite (canonical perft counts included); CI runs it on 3.10–3.12 |
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
