# Leaderboard Governance

What appears on a leaderboard, how it is ranked, and how much to trust it.

There are **two** leaderboards in v0.3. They differ in one critical property:
whether entries are **verified**.

| | Verified (hosted) | Self-reported (local) |
| --- | --- | --- |
| Code | `verified_leaderboard`, `bench/ceb/hosted/db.py` | `compute_leaderboard`, `bench/ceb/scoring/track_a.py` |
| Source of entries | `results` rows in the hosted SQLite DB | `<results>/*/state.json` scan (default `runs/`) |
| `verified` flag | `True` (worker-minted only) | always `False` |
| CLI | `ceb hosted leaderboard --db --track` | `ceb leaderboard compute --track --results` |
| API | `GET /api/hosted/leaderboard?track=A` | `GET /api/leaderboard?track=A` |

## Verified vs unverified

**Only the hosted official worker mints `verified:true`.** A result is verified
only if it was produced by `run_official_eval` (`bench/ceb/hosted/official_eval.py`)
via `ceb hosted worker run-once`. That path:

1. static anti-cheating scan of the snapshot,
2. strict gate against the **private** eval pack,
3. `official_round` or `final_eval` with the private pack (optional engine
   jail),
4. public/private artifact split,
5. reproducibility metadata + signing,
6. result recorded with `verified=1` in the DB.

The worker **refuses to verify** — no verified result is written — when there
is no private eval pack, the scan fails, or the strict gate fails.

**Local rankings are never verified.** `compute_leaderboard` scans
`state.json` files written by local `ceb round run` invocations and stamps
every entry `verified: false`. These are self-reported by whoever ran the
command; the harness does not attest to them. The local board's payload sets
`verified_only: false` to make this explicit.

## Selection rule

Both boards rank **one entry per run**, best score first, using the same
priority:

1. **best `final_eval`** result if any exists, else
2. **best `official_round`** result, else
3. **nothing** — the run does not place.

**Quick rounds never count** toward a ranking. The hosted worker never marks a
quick result verified, so quick can never reach the verified board. On the
local board, quick is excluded unless `--include-quick` is set, which is a
**diagnostic** view (best score across *all* modes, including quick) and is
never an official ranking — its payload still reports `verified_only: false`.

**Legacy "official" counts.** The pre-v0.3 mode name `official` is treated as
an official round: `OFFICIAL_MODES = {"official", "official_round"}`
(`track_a.py`), and the hosted query matches `mode in ("official_round",
"official")`. Local rounds recorded with no `mode` field default to `official`.

Eval modes are defined in `bench/ceb/rounds/round_runner.py` and
`tracks/a_from_scratch/scoring.yaml`:

| Mode | Budget | Gate | games/opponent | openings |
| --- | --- | --- | --- | --- |
| `quick` | free | non-strict | 2 | 2 |
| `official_round` | 1 of 3 units | strict | 4 | 6 |
| `final_eval` | none | strict | 8 | 8 |

## What makes a result eligible

For the **verified board** an entry must be a DB `results` row with
`verified=1`, a non-null `score`, and mode `final_eval`, `official_round`, or
legacy `official`. Only the worker writes such rows.

For the **local board** an entry must come from a readable `state.json` whose
`track` matches, containing at least one round with a non-null `score` in an
eligible mode. Unreadable / non-JSON state files are skipped silently. Each
entry also reports `gate_passed`, `rounds_played`, and
`official_rounds_played` for context.

## Integrity caveats

- **Self-reported runs are not authoritative.** `compute_leaderboard` output
  (CLI `ceb leaderboard compute`, API `/api/leaderboard`) is a convenience /
  diagnostic view. Entries are computed from local state the runner controls;
  there is no scan, no private-pack enforcement, no signing. Do not treat them
  as official standings.
- **Verified results carry symmetric signatures only.** The verified board
  reflects worker-produced results, which are signed with **symmetric**
  HMAC-SHA256 (see `docs/RESULT_SIGNING.md`). Authenticity is confirmable only
  by holders of `CEB_SIGNING_KEY` — there is **no public-key attestation** in
  v0.3. A consumer without the key takes the operator's word for it.
- **Verified-only is the public-facing default.** `ceb hosted leaderboard` and
  `GET /api/hosted/leaderboard` return verified entries only; the unverified
  local board exists for self-checking, not for publishing rankings.
