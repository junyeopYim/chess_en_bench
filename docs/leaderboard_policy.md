# Leaderboard Policy

How runs are ranked. Implementation: `compute_leaderboard` in
`bench/ceb/scoring/track_a.py`, exposed via the `ceb leaderboard compute`
CLI and the `/api/leaderboard` endpoint (`bench/ceb/api/main.py`).

## Ranking rule: best verified-eligible result per run

The local leaderboard scans `<results>/*/state.json` (default `runs/`). For
each run whose `track` field matches the requested track:

1. Walk the run's recorded rounds.
2. Select, per run, the best (`score` not null) `final_eval` result if any
   exists, otherwise the best `official_round`. Rounds recorded as `official`
   (legacy runs written before modes were renamed) count as official rounds.
   Quick rounds never count.
3. The run's leaderboard score is that selected score; the entry records
   which round produced it (`best_round`: round number, score, mode).
4. Runs are sorted best-first; unreadable or non-JSON `state.json` files are
   skipped silently.

Each entry contains: `run_id`, `workspace`, `gate_passed`, `rounds_played`
(all rounds), `official_rounds_played` (official + final, excluding quick),
`best_round`, `score`, and `verified`. This scanner reads self-reported local
runs, so `verified` is always `false` and the board JSON sets
`verified_only: false`. Cryptographically **verified** official results come
only from the hosted worker; see `docs/LEADERBOARD_GOVERNANCE.md`. Output
schema is `ceb.leaderboard/v1` with an `include_quick` field recording which
view produced the board.

## Why quick rounds are excluded

Quick rounds exist for fast iteration: they are free and unlimited, run the
non-strict gate, play only 2 opponents at 50 ms movetime, and use a smaller
opening subset. Their ladder scores are not comparable to official rounds
(different opponent pool means a different performance mean), and counting
free unlimited rounds would let a run reroll its score at no cost. Official
rounds consume budget (3 per run), require the strict gate (`go perft`
mandatory), and play the full six-opponent pool — only they count.

## Diagnostic view: --include-quick

`ceb leaderboard compute --include-quick` (API:
`/api/leaderboard?include_quick=true`) also considers quick rounds. The CLI
output is labelled "diagnostic view: quick rounds INCLUDED — not an official
ranking" and the JSON sets `include_quick: true`. Use it to sanity-check a
workspace before spending budget; never publish it as a ranking.
`best_round.mode` shows whether a diagnostic entry's best came from a quick
round.

## What makes a round valid

A round appears in `state.json` only if it actually ran, which requires
(enforced by `bench/ceb/rounds/round_runner.py` and `rounds/state.py`):

- The gate passed — re-run at the start of every round, and a failing gate
  aborts the round before any match. Official rounds always use the strict
  gate; quick rounds use the public (non-strict) gate.
- For official rounds, budget remained (3 official rounds per run; quick
  rounds are free and do not consume budget).

The recorded `score` is the `final_score` from the round's
`ceb.score.track_a/v1` report (ladder score minus penalties). It is null
when no opponent pairing produced any rated games; null-score rounds never
become a run's best round.

## Ties and nulls

The sort key is `(score is None, -score)`:

- Runs with no qualifying scored round (`score` null) sort after all scored
  runs; among themselves they keep scan order.
- Exact score ties keep scan order too (Python's sort is stable), and the
  scan iterates `sorted(glob("*/state.json"))` — so ties break
  alphabetically by run directory name. There is no head-to-head or
  fewest-rounds tiebreaker.

## Usage

```bash
# CLI: rank all runs under runs/ for Track A, optionally write JSON
ceb leaderboard compute --track A --results runs --json-out leaderboard.json

# API + dashboard
ceb server start --host 127.0.0.1 --port 8000
curl http://127.0.0.1:8000/api/leaderboard            # official rounds only
curl "http://127.0.0.1:8000/api/leaderboard?include_quick=true"
```

The API serves the same `compute_leaderboard` output over the server's
configured runs directory. For Track B it returns an empty `entries` list
with a note: Track B rounds are scored individually
(`ceb track-b round run`, delta Elo vs the pinned baseline) and have no
aggregated leaderboard yet — that aggregation is planned, not implemented.

## Integrity caveats (read before trusting numbers)

All leaderboard inputs are self-reported files on the local disk:

- `state.json` and round reports are plain JSON written by the harness with
  no signing or tamper detection — anyone with file access can edit a score.
- No hidden test data ships in this repository. Operators can mount a
  private eval pack (`--eval-pack`, or `CEB_PRIVATE_EVAL_DIR` for official
  rounds), but the leaderboard cannot tell which pack produced a score
  beyond the `eval_pack` field in the round report.
- `gate_passed` in an entry is informational. The leaderboard does not
  exclude runs with a failed gate flag, although the round runner itself
  refuses to start rounds without a passing gate.
- The Docker evaluator sandbox (`--sandbox docker`) is recommended for
  untrusted submissions but optional; the leaderboard does not record or
  verify whether it was used.

For any comparison that matters, re-run the official rounds yourself from
the submitted workspace (`ceb round run --sandbox docker`) rather than
trusting a copied `runs/` directory.
