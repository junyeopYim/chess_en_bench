# Track A — from-scratch chess engine

Track A measures whether an agent can build a working UCI chess engine without
external chess libraries, then improve it against a fixed opponent ladder.
Everything described here is implemented and runs locally; no hidden data is
shipped, but operators may mount a private eval pack for official rounds (see
"Eval packs"). Track config: `tracks/a_from_scratch/track.yaml` (3 official
rounds per run, unlimited gate attempts, final score = best valid round). The
official leaderboard counts official rounds only.

## From-scratch requirement

The submission must implement its own chess logic: board representation, move
generation, legality, and search. External chess libraries and engines are
forbidden in the submission — no python-chess, no Stockfish bindings, no
downloaded engine binaries, opening books, or tablebases. Any language is
acceptable as long as the workspace yields a runnable `./engine`.

This is enforced behaviorally (every move is validated by the benchmark's own
oracle in `bench/ceb/chess/`; perft counts are cross-checked) and by
inspection of the workspace. There is no automated library scanner yet.

## Submission layout

A workspace needs one of:

- `engine` — executable speaking the UCI subset in `specs/uci_minimal.md`, or
- `build.sh` — script (120 s limit) that produces `./engine`; the gate runs it.

```bash
ceb workspace prepare --track A --run-id myrun    # creates runs/myrun/workspace
```

A working reference: `examples/submissions/minimal_uci_engine_python/`. For a
prepared workspace (`runs/<run_id>/workspace` next to `state.json`) the round
runner infers the run id from the parent directory; `--run-id` overrides.

## The public gate (unlimited attempts)

```bash
ceb gate run --track A --workspace runs/myrun/workspace [--strict] [--json-out F] [--no-match]
```

The gate never consumes round budget. Checks run in order; a hard failure
skips the remaining heavy checks. Exit code 0 on pass, 2 on fail. The JSON
report (schema `ceb.gate.report/v1`, including a `strict` field) is saved
under `runs/_gate/` unless `--json-out` is given. Bestmove/perft failure
details quote row ids only, never FENs.

| # | Check | Verifies | Severity |
| --- | --- | --- | --- |
| 1 | format | `engine` or `build.sh` present in the workspace | hard |
| 2 | build | `build.sh` exits 0 within 120 s (skipped if prebuilt) | hard |
| 3 | engine | `./engine` exists and is executable | hard |
| 4 | handshake | `uci`/`uciok`, `isready`/`readyok` | hard |
| 5 | position | `position startpos` / `fen ...` / `moves ...` accepted | hard |
| 6 | bestmove | legal bestmove on the pack FENs, oracle-validated | hard |
| 7 | perft | `go perft` counts match the oracle (depth ≤ 3) | soft / hard in strict |
| 8 | time | bestmove for `go movetime 100` within 100 + 2500 ms | hard |
| 9 | mini_match | 2 games vs BenchRandom at 50 ms/move, zero candidate faults | hard |

In the default (non-strict) mode the `go perft` extension
(`specs/uci_extension_perft.md`) is recommended — missing support only warns,
but wrong node counts fail the gate. In **strict** mode (`--strict`, and
ALWAYS used by official rounds) perft is a hard check: missing support OR
wrong counts fails the gate and skips the remaining checks. An engine without
correct perft cannot score officially. All tunables (timeouts, movetimes,
mini-match size) are public in `tracks/a_from_scratch/public/gate_config.yaml`:
handshake timeout 8 s, bestmove movetime 200 ms + 3000 ms grace, at most 2
bestmove failures reported. For untrusted submissions, run with
`--sandbox docker` (`docs/security.md`).

## Round modes

```bash
ceb round run --track A --workspace runs/myrun/workspace --round 1 --quick   # free
ceb round run --track A --workspace runs/myrun/workspace --round 2           # spends budget
```

Every round re-runs the gate first; a failing gate aborts the round without
consuming budget. Official rounds run the strict gate (perft mandatory);
quick rounds run the non-strict gate. From `tracks/a_from_scratch/scoring.yaml`:

| Mode | Gate | Opponents | Games each | movetime | max plies | Openings | Anchors | Budget |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| quick | non-strict | BenchRandom, BenchMaterial1 | 2 | 50 ms | 120 | first 2 | [] | free |
| official | strict | all six (ladder order below) | 4 | 200 ms | 200 | first 6 | [] | 1 of 3 per run |

The internal runner (`bench/ceb/match/internal_runner.py`) alternates colors,
seeds each game, validates every move against the oracle, and adjudicates
draws at the ply cap and via the fifty-move rule. Artifacts land in
`runs/<run_id>/round_N/`: per-opponent `match_vs_*.json` (with per-game
`opening_id` and an `openings` list), UCI-movetext game files, `report.json`
(`ceb.round.report/v1`, with `openings_used`, `strict_gate`, `eval_pack`),
and `feedback.json` (`ceb.round.feedback/v1`) — aggregate-only: per-opponent
W/D/L and score rates, fault counts, scores, generic advice. No move logs, no
FENs, and no opening ids are fed back.

## Opening suite

Games start from a validated opening suite, not always from `startpos`. The
canonical format (`bench/ceb/match/openings.py`) is JSONL, one opening per
line: `{"id", "fen": "startpos"|FEN, "moves": [UCI...], "tags": [...]}`.
Every move is oracle-validated at load time (`OpeningError` on anything
illegal). The public suite is
`tracks/a_from_scratch/public/openings_public.jsonl` (8 openings); the `.pgn`
file remains for human readers only. Each round mode takes the first
`openings_limit` openings of the resolved suite (quick 2, official 6).
Openings are played in pairs — the same opening with colors swapped, so the
candidate plays each opening as both white and black;
`pairs = ceil(games_per_opponent / 2)`. Across the round the suite is rotated
per opponent (opponent `j` starts at offset `j·pairs`, wrapping), so a round
covers more openings than any single match.

## Eval packs

The data an evaluation consumes is bundled as a pack (`bench/ceb/eval_pack.py`).
The public pack = `fen_examples.jsonl` + `perft_examples.jsonl` +
`openings_public.jsonl`. A private pack is a directory with any of
`fen_hidden.jsonl` / `perft_hidden.jsonl` / `openings_hidden.jsonl` plus an
optional `manifest.json` (`{"name", "openings_mode": "extend"|"replace"}`,
default extend); private rows always get ids so reports never quote a hidden
FEN. Resolution: an explicit `--eval-pack <dir>` flag applies anywhere; the
`CEB_PRIVATE_EVAL_DIR` env var applies only to official rounds and the strict
gate. No hidden data ships in this repo; `examples/eval_packs/tiny_private/`
is a fake demo pack used by tests. `--eval-pack` is not supported together
with `--sandbox docker`.

## Anchors (optional)

`tracks/a_from_scratch/scoring.yaml` defines limited-strength anchor engines
(`anchor_opponents`: SF18_UCI_Elo_1320/1600/1900/2200 — engine binary name,
`uci_elo`, `rating`). A round plays an anchor only when its name is listed in
the mode's `anchors` list (empty by default). When the engine binary is not
on PATH, the round runner skips the anchor with a progress note instead of
failing; when present it sends `UCI_LimitStrength`/`UCI_Elo`. Anchors are
never required in CI.

## Opponent pool

Benchmark-owned, deterministic given a seed (set per game by the runner), and
runnable standalone: `python -m ceb.match.opponents BenchRandom`.

| Name | Nominal rating | Move selection |
| --- | --- | --- |
| BenchRandom | 400 | uniform random legal move |
| BenchGreedyCapture | 600 | highest-value capture if any (incl. en passant), else random |
| BenchMaterial1 | 800 | depth-1 negamax, material-only eval |
| BenchPST1 | 1000 | depth-1 negamax, material + center/pawn-advance square bonuses |
| BenchMiniMax2 | 1200 | depth-2 negamax, material-only eval |
| BenchAlphaBeta3 | 1400 | depth-3 alpha-beta, material + square bonuses |

Depth-based opponents iteratively deepen within `go movetime` and fall back to
the deepest completed depth; ties between equal moves break via the seeded RNG.

## Scoring summary

Per opponent (`bench/ceb/scoring/elo.py`, `bench/ceb/scoring/track_a.py`):

- `score_rate = (W + 0.5·D) / games`, clamped into (0, 1) by `eps = 1 / (2·(games+1))`
- `delta_elo = −400 · log10(1/rate − 1)`
- `performance = opponent_rating + delta_elo`

`ladder_score` = mean performance across opponents. Penalty per candidate
fault: illegal_move 30, timeout 15, crash 25 points. Round
`final_score = ladder_score − penalties` (schema `ceb.score.track_a/v1`). The
run's score is its **best valid official round**; rank runs with:

```bash
ceb leaderboard compute --track A --results runs [--json-out F]
```

Only official rounds count; `--include-quick` is a diagnostic view (labeled
as such in the output), never an official ranking.

## Public data files (`tracks/a_from_scratch/public/`)

| File | Contents |
| --- | --- |
| `fen_examples.jsonl` | 10 tagged FENs (castling, en passant, promotion, endgames) used by the gate's bestmove check |
| `perft_examples.jsonl` | 10 position/depth/node rows (startpos, Kiwipete, CPW positions) used by the perft check |
| `gate_config.yaml` | public gate tunables (read by the gate runner) |
| `openings_public.jsonl` | the canonical public opening suite (8 openings) used as game start positions |
| `openings_public.pgn` | the same lines in PGN, for human readers only — not parsed by the runner |

Agents may read all of these. Official rounds may additionally use an
operator-mounted private pack; its contents never appear in agent feedback.
