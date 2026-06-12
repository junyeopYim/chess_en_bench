# Track A — private evaluation packs (mount point)

**This repository ships no hidden data.** This directory is empty apart from
this README and exists to keep the conventional mount path in git. The loader
is real: `bench/ceb/eval_pack.py` reads operator-managed private pack
directories and merges them with the public Track A data.

The full eval-pack interface — public files, private pack files
(`fen_hidden.jsonl`, `perft_hidden.jsonl`, `openings_hidden.jsonl`,
`manifest.json`), hidden-row id assignment, hidden-safe loading, resolution
rules, the combine-with-jail guarantee, and `eval_pack_hash` versioning — is
documented once in **[`docs/EVAL_PACKS.md`](../../../docs/EVAL_PACKS.md)**. The
notes below are the Track A specifics.

## Resolution for Track A

- `--eval-pack <dir>` on `ceb gate run`, `ceb round run`, and
  `ceb hosted worker run-once` loads a pack explicitly, anywhere.
- `CEB_PRIVATE_EVAL_DIR` is consumed only by evaluations that opt in: the
  strict gate (`ceb gate run --strict`) and official rounds. The plain public
  gate and quick rounds never read it.
- Nothing reads this directory implicitly — a deployment must point the flag
  or env var at it (or any other operator-managed path).
- `--eval-pack` combines with `--engine-jail docker` (the pack is read
  host-side and never mounted), but is **not** supported with the legacy
  `--sandbox docker` mode.

A fake demo pack with the exact layout lives at
`examples/eval_packs/tiny_private/`; the test suite exercises it.

## Status

| Piece | State |
|---|---|
| Private pack loader (`bench/ceb/eval_pack.py`) | Implemented |
| Demo pack + tests (`examples/eval_packs/tiny_private/`) | Implemented |
| Real hidden FEN/perft/opening data | Not shipped — operator-managed, mounted per deployment |
| Hidden opponents | Not part of the pack interface (anchor engines are configured in `../scoring.yaml` instead) |

Results that depend on hidden packs reach the agent only through the sanitized
feedback contract (`specs/round_feedback_contract.md`).
