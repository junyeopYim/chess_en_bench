# Leaderboard Policy

How runs are ranked. Implementation: `compute_leaderboard` in
`bench/ceb/scoring/track_a.py`, exposed via the `ceb leaderboard compute`
CLI and the `/api/leaderboard` endpoint (`bench/ceb/api/main.py`).

## Ranking rule: best valid round per run

The leaderboard scans `<results>/*/state.json` (default `runs/`). For each
run whose `track` field matches the requested track:

1. Walk the run's recorded rounds.
2. Keep rounds whose `score` is not null.
3. The run's leaderboard score is the **maximum** such score; the entry
   records which round produced it (`best_round`: round number, score, mode).
4. Runs are sorted best-first; unreadable or non-JSON `state.json` files are
   skipped silently.

Each entry contains: `run_id`, `workspace`, `gate_passed`, `rounds_played`,
`best_round`, `score`. Output schema: `ceb.leaderboard/v1`.

## What makes a round valid

A round appears in `state.json` only if it actually ran, which requires
(enforced by `bench/ceb/rounds/round_runner.py` and `rounds/state.py`):

- The public gate passed — the gate is re-run at the start of every round,
  and a failing gate aborts the round before any match.
- For official rounds, budget remained (3 official rounds per run; quick
  rounds are free and do not consume budget).

The recorded `score` is the `final_score` from the round's
`ceb.score.track_a/v1` report (ladder score minus penalties). It is null
when no opponent pairing produced any rated games; null-score rounds never
become a run's best round.

**Note (v0.1 behavior):** `compute_leaderboard` does not filter by round
mode, so a quick round's score also counts toward "best" if it happens to
be the highest. Quick rounds use a reduced opponent set (2 opponents,
shorter movetime), so their ladder scores are not directly comparable to
official rounds. The `best_round.mode` field exposes this — check it when
comparing entries.

## Ties and nulls

The sort key is `(score is None, -score)`:

- Runs with no scored round (`score` null) sort after all scored runs; among
  themselves they keep scan order.
- Exact score ties keep scan order too (Python's sort is stable), and the
  scan iterates `sorted(glob("*/state.json"))` — so ties break
  alphabetically by run directory name. There is no head-to-head or
  fewest-rounds tiebreaker in v0.1.

## Usage

```bash
# CLI: rank all runs under runs/ for Track A, optionally write JSON
ceb leaderboard compute --track A --results runs --json-out leaderboard.json

# API + dashboard
ceb server start --host 127.0.0.1 --port 8000
curl http://127.0.0.1:8000/api/leaderboard          # track A (default)
curl "http://127.0.0.1:8000/api/leaderboard?track=B"
```

The API serves the same `compute_leaderboard` output over the server's
configured runs directory. For Track B it returns an empty `entries` list
with a note: a Track B leaderboard requires the candidate-vs-baseline
evaluation pipeline, which is planned but not implemented in v0.1 (only the
scoring module, diff checker, and status command ship — see
`docs/scoring.md`).

## Integrity caveats (read before trusting numbers)

v0.1 is a local MVP. All inputs are self-reported files on the local disk:

- `state.json` and round reports are plain JSON written by the harness with
  no signing or tamper detection — anyone with file access can edit a score.
- There is no hidden test data; `tracks/*/private/` directories are
  documented placeholders. Everything the leaderboard sees was produced on
  the submitter's machine.
- `gate_passed` in an entry is informational. The leaderboard does not
  exclude runs with a failed gate flag, although the round runner itself
  refuses to start rounds without a passing gate.
- Engines run as ordinary local processes (argv-only spawning, read
  timeouts, process-group kill). Docker sandboxing is recommended in the
  docs but not implemented in v0.1.

For any comparison that matters, re-run the rounds yourself from the
submitted workspace (`ceb gate run`, then `ceb round run`) rather than
trusting a copied `runs/` directory.
