# Round Feedback Contract — `ceb.round.feedback/v1`

This is the only round-result document intended for the submitting agent.
It is produced by `make_feedback()` in `bench/ceb/rounds/feedback.py`, called
at the end of every round by `run_round()` in `bench/ceb/rounds/round_runner.py`,
and written to `runs/<run_id>/round_<N>/feedback.json`. The same content is
rendered as text by `feedback_to_text()` and printed by `ceb round run`.

Generate one:

```bash
ceb round run --track A --workspace <dir> --round 1 --quick
cat runs/<run_id>/round_1/feedback.json
```

## Fields

| Field | Type | Meaning |
|---|---|---|
| `schema` | string | Constant `"ceb.round.feedback/v1"`. |
| `round` | integer | Round number, as passed to `ceb round run --round N`. |
| `mode` | string | `"quick"` (free smoke round) or `"official"` (consumes budget). |
| `per_opponent` | array of objects | One entry per opponent, in the order matches were played. See below. |
| `faults` | object | Candidate fault totals across all matches in the round: `{"illegal": int, "timeout": int, "crash": int}`. |
| `penalty_points` | number | `illegal*30 + timeout*15 + crash*25` (weights from `tracks/a_from_scratch/scoring.yaml`). |
| `ladder_score` | number or null | Mean per-opponent performance rating, rounded to 1 decimal. Null if no games were scored. |
| `final_score` | number or null | `ladder_score - penalty_points`, rounded to 1 decimal. This is the round's score; a run's final score is its best valid round. |
| `advice` | array of strings | Generic, fixed-template hints keyed only off the fault counters (one hint per fault kind present; one generic hint when there are no faults). |

Each `per_opponent` entry:

| Field | Type | Meaning |
|---|---|---|
| `opponent` | string | Public opponent name (see `tracks/a_from_scratch/opponents/README.md`). |
| `games` | integer | Games counted (`wins + draws + losses`). |
| `wins`, `draws`, `losses` | integer | Results from the candidate's perspective. |
| `score_rate` | number or null | `(W + 0.5*D) / games`, clamped into `[eps, 1-eps]` with `eps = 1/(2*(games+1))`, rounded to 4 decimals. Null when `games == 0`. |

The feedback is a strict subset of the full round report's `score` block
(`ceb.score.track_a/v1`, computed in `bench/ceb/scoring/track_a.py`). It drops
the per-opponent `opponent_rating`, `delta_elo`, and `performance` fields, but
all of those are recomputable from `score_rate` and the public formulas in
`bench/ceb/scoring/elo.py` — nothing in the feedback depends on secrets.

## Sanitization guarantees

Feedback is aggregate-only by design, so agents can iterate between rounds
without the evaluation channel leaking anything they do not already have:

- No move logs: no PGN, no UCI movetext, no individual game records, and no
  per-game results — only W/D/L totals per opponent.
- No positions: no FENs, no opening lines, no test positions of any kind.
- No hidden data: nothing sourced from `tracks/*/private/` ever appears here.
- `advice` strings are fixed templates triggered solely by the `illegal`,
  `timeout`, and `crash` counters; they never echo game or position content.
- Everything in the document is derived from `round_report["score"]` plus the
  round number and mode — no other inputs.

Honest caveat for v0.1: this is a local MVP, so the full round report
(`report.json`), per-match reports (`match_vs_<Opponent>.json`), and game
movetext files (`games_vs_<Opponent>.txt`) are written to the same
`runs/<run_id>/round_<N>/` directory on local disk. The contract defines what
an agent-facing harness returns to the agent; in a hosted deployment only
`feedback.json` would cross that boundary.

## Example payload

A plausible official round (4 games per opponent, so `eps = 0.1`; the two 4-0
sweeps are clamped from 1.0 to 0.9):

```json
{
  "schema": "ceb.round.feedback/v1",
  "round": 1,
  "mode": "official",
  "per_opponent": [
    {"opponent": "BenchRandom",        "games": 4, "wins": 4, "draws": 0, "losses": 0, "score_rate": 0.9},
    {"opponent": "BenchGreedyCapture", "games": 4, "wins": 4, "draws": 0, "losses": 0, "score_rate": 0.9},
    {"opponent": "BenchMaterial1",     "games": 4, "wins": 3, "draws": 1, "losses": 0, "score_rate": 0.875},
    {"opponent": "BenchPST1",          "games": 4, "wins": 2, "draws": 1, "losses": 1, "score_rate": 0.625},
    {"opponent": "BenchMiniMax2",      "games": 4, "wins": 1, "draws": 1, "losses": 2, "score_rate": 0.375},
    {"opponent": "BenchAlphaBeta3",    "games": 4, "wins": 0, "draws": 1, "losses": 3, "score_rate": 0.125}
  ],
  "faults": {"illegal": 0, "timeout": 1, "crash": 0},
  "penalty_points": 15,
  "ladder_score": 1027.2,
  "final_score": 1012.2,
  "advice": [
    "Timeouts detected: respect 'go movetime' and always answer with a bestmove line."
  ]
}
```

When there are no faults, `advice` contains the single generic hint that
search depth and evaluation are the main levers for a higher ladder score.
