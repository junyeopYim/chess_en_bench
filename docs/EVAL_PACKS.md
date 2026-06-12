# Evaluation packs

An evaluation pack is the data an evaluation consumes. It has a **public**
part that ships in this repository and an optional **private** part that an
operator mounts at evaluation time. The loader is `bench/ceb/eval_pack.py`;
opening validation lives in `bench/ceb/match/openings.py`.

**No real hidden data ships in this repository.** The only private pack in the
tree is the fake demo at `examples/eval_packs/tiny_private/`, which exists so
the loader and tests have a documented shape to exercise. Real hidden FENs,
perft expectations, and openings are operator-managed and mounted per
deployment.

## Public pack

The public pack is the Track A `public/` directory, loaded by
`load_public_pack()`:

| File | Rows | Format |
|---|---|---|
| `tracks/a_from_scratch/public/fen_examples.jsonl` | bestmove-legality positions | `{"id", "fen", "tags"}` |
| `tracks/a_from_scratch/public/perft_examples.jsonl` | perft expectations | `{"id", "fen", "depth", "nodes"}` |
| `tracks/a_from_scratch/public/openings_public.jsonl` | opening suite | `{"id", "fen": "startpos"\|FEN, "moves": [UCI...], "tags": [...]}` |

The resulting `EvalPack` has `source = "public"`.

## Private pack directory

A private pack is a **directory** containing any of these files (at least one
is required); their row formats match the public files exactly:

| File | Extends | Row format |
|---|---|---|
| `fen_hidden.jsonl` | public FENs | `{"id", "fen", "tags"}` |
| `perft_hidden.jsonl` | public perft | `{"id", "fen", "depth", "nodes"}` |
| `openings_hidden.jsonl` | public openings (see `openings_mode`) | `{"id", "fen": "startpos"\|FEN, "moves": [UCI...], "tags": [...]}` |
| `manifest.json` | optional | `{"name": ..., "openings_mode": "extend"\|"replace"}` |

`manifest.json` keys (both optional):

- `name` — the pack name reported in artifacts (defaults to the directory
  name). Other keys (e.g. a `note`) are ignored.
- `openings_mode` — `"extend"` (default) appends hidden openings to the public
  suite; `"replace"` uses the hidden openings only. FEN and perft rows
  **always extend** the public sets; only openings honor `openings_mode`.

When a private pack is resolved, the `EvalPack.source` becomes
`"public+private"`.

### Id assignment for hidden rows

Every row is guaranteed an `id`. If a private row omits one, the loader
assigns:

- `hidden_fen_<line>` in `fen_hidden.jsonl`
- `hidden_perft_<line>` in `perft_hidden.jsonl`
- `opening_<line>` in `openings_hidden.jsonl`

Hidden rows are also tagged internally (`hidden: true`). Because every row has
an id, gate failures, round reports, and feedback can reference a hidden row
by id and never need to quote a hidden FEN or move.

### Hidden-safe loading

Private files load with `hidden=True`. FENs and opening moves are validated at
load time (FENs through `parse_fen`, opening moves against the internal move
oracle), so a corrupt pack fails loudly instead of feeding an illegal position
into a match. The error messages stay leak-free: a hidden validation error
quotes the **file basename + row id + "content withheld"** and never the FEN,
move, or full path. The full detail is kept only on the exception's
`private_message` for operator logs (`bench/ceb/sanitize.py`).

## Resolving a pack

`resolve_eval_pack(root, private_dir=None, allow_env=False)` always loads the
public pack, then merges a private pack if one is resolved. Two ways to supply
the private directory:

1. **`--eval-pack <dir>`** — explicit flag, honored anywhere it is accepted:
   `ceb gate run`, `ceb round run`, `ceb track-b round run`,
   `ceb track-b official run`, and `ceb hosted worker run-once`.
2. **`CEB_PRIVATE_EVAL_DIR`** — environment fallback, consumed **only** by
   evaluations that opt in (`allow_env=True`): the strict Track A gate
   (`ceb gate run --strict`), official Track A rounds, and **all** Track B
   rounds (`bench/ceb/track_b/round_runner.py` passes `allow_env=True`). The
   plain public gate and Track A quick rounds pass `allow_env=False`, so they
   never read the env var.

Nothing reads a private directory implicitly. The conventional mount points
(`tracks/a_from_scratch/private/`, `tracks/b_stockfish_opt/private/`) are empty
placeholders — a deployment must point the flag or env var at an
operator-managed directory.

```bash
# Strict Track A gate with a private pack
ceb gate run --track A --workspace <ws> --strict --eval-pack <private-dir>

# Official Track A round with a private pack
ceb round run --track A --workspace <ws> --round 1 --eval-pack <private-dir>

# Hosted worker (private pack is REQUIRED to produce a verified result)
ceb hosted worker run-once --db runs/hosted.sqlite \
    --eval-pack <private-dir> --engine-jail docker
```

## Combining with the engine jail

A hidden pack combines safely with `--engine-jail docker`. The **evaluator
stays on the host** and reads the pack there; the jailed engine only ever sees
individual `position fen ...` UCI lines on its stdin. The pack directory is
**never mounted** into the jail container — the jail mounts only the
submission workspace, read-only, at `/submission`
(`bench/ceb/jail/docker_engine.py`).

Because of this split, `--eval-pack` works **together with `--engine-jail
docker`**. This is unlike the legacy `--sandbox docker` mode (harness-in-
container), which still **rejects** `--eval-pack`: that mode would have to
mount the pack inside the container, so `ceb round run --sandbox docker
--eval-pack ...` aborts with a message pointing you at `--engine-jail docker`
or `--sandbox none`. Official hosted evaluation uses `--engine-jail docker`,
not `--sandbox`.

## Versioning a pack: eval_pack_hash

Official-result metadata records the pack you used so results are reproducible
and tamper-evident (`bench/ceb/hosted/metadata.py`):

- `eval_pack_id` — the pack name (from `manifest.json` or the directory name).
- `eval_pack_hash` — a deterministic `sha256:` over the pack directory's
  relative paths and file contents (`hash_directory`), or `null` when no
  private pack was used.

Treat the pack directory as versioned content: change any row and the hash
changes, so two runs are only comparable when their `eval_pack_hash` matches.

## The tiny_private demo pack

`examples/eval_packs/tiny_private/` shows the exact layout and is exercised by
the test suite (`tests/test_eval_pack.py`, and as the stand-in private pack in
`tests/test_hosted.py`, `tests/test_engine_jail.py`, and others). It is
**fake demonstration data, not a real hidden pack**:

```
examples/eval_packs/tiny_private/
  manifest.json          {"name": "tiny_private_example", "openings_mode": "extend", ...}
  fen_hidden.jsonl       2 endgame positions
  perft_hidden.jsonl     2 perft expectations
  openings_hidden.jsonl  2 opening lines
```

Use it to dry-run the loader and CLI flags before pointing them at a real
operator pack:

```bash
ceb round run --track A --workspace <ws> --round 1 \
    --eval-pack examples/eval_packs/tiny_private
```
