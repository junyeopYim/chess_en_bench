# Track A — private evaluation packs (mount point)

**This repository ships no hidden data.** This directory is empty apart from
this README and exists to keep the conventional mount path in git. The
loader, however, is real: `bench/ceb/eval_pack.py` reads operator-managed
private pack directories and merges them with the public data.

## Pack layout

A private pack is a directory containing any of (at least one required):

- `fen_hidden.jsonl` — extra bestmove-legality positions. Same row format as
  `../public/fen_examples.jsonl`: `{"id", "fen", "tags"}`.
- `perft_hidden.jsonl` — extra perft expectations. Same row format as
  `../public/perft_examples.jsonl`: `{"id", "fen", "depth", "nodes"}`.
- `openings_hidden.jsonl` — extra opening lines in the canonical JSONL
  format (`bench/ceb/match/openings.py`):
  `{"id", "fen": "startpos"|FEN, "moves": [UCI...], "tags": [...]}`.
  Every move is oracle-validated; an illegal move fails the load loudly.
- `manifest.json` — optional:
  `{"name": ..., "openings_mode": "extend"|"replace"}`. `extend` (default)
  appends hidden openings to the public suite; `replace` substitutes it.
  FEN and perft rows always extend the public sets.

Rows in private files are always assigned ids when missing
(`hidden_fen_<line>`, `hidden_perft_<line>`, `opening_<line>`), so gate
failure details, round reports, and feedback can reference hidden rows by id
without ever quoting a hidden FEN or move.

## Resolution rules

- `--eval-pack <dir>` on `ceb gate run`, `ceb round run`, and
  `ceb track-b round run` loads a pack explicitly, anywhere.
- The `CEB_PRIVATE_EVAL_DIR` environment variable is consumed only by
  evaluations that opt in (`allow_env`): official rounds and the strict
  gate. The standalone public gate and quick rounds never read it.
- Nothing reads this directory implicitly — a deployment must point the flag
  or env var at it (or at any other operator-managed path).
- `--eval-pack` is not supported together with `--sandbox docker`.

A fake demo pack with the exact layout lives at
`examples/eval_packs/tiny_private/`; the test suite exercises it.

## Status

| Piece | State |
|---|---|
| Private pack loader (`bench/ceb/eval_pack.py`) | Implemented |
| Demo pack + tests (`examples/eval_packs/tiny_private/`) | Implemented |
| Real hidden FEN/perft/opening data | Not shipped — operator-managed, mounted per deployment |
| Hidden opponents | Not part of the pack interface (anchor engines are configured in `../scoring.yaml` instead) |

Results that depend on hidden packs reach the agent only through the
sanitized feedback contract (`specs/round_feedback_contract.md`).
