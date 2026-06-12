# Licensing

How the repository, the Stockfish baseline, and participant artifacts are
licensed. This is a practical summary, not legal advice; the authoritative
texts are `LICENSE` and `NOTICE` at the repository root.

## This repository: MIT

Everything authored in this repository is MIT-licensed (see `LICENSE`,
copyright 2026 junyeopYim): the benchmark harness (`bench/ceb/`), the internal
chess oracle (`bench/ceb/chess/`), the benchmark opponents
(`bench/ceb/match/opponents.py`), the gate and scoring code, the CLI, the
track configs (`tracks/`), specs, docs, scripts, the static web UI, and the
example submissions under `examples/submissions/`.

You can use, modify, and redistribute all of that under the usual MIT terms
(keep the copyright notice and license text).

## Stockfish: GPLv3, not distributed

Track B evaluates patches against Stockfish, which is licensed under the GNU
General Public License v3. As stated in `NOTICE`:

- **Stockfish sources are NOT distributed with this repository.**
- `scripts/setup_stockfish.sh` fetches the pinned release (Stockfish 18, tag
  `sf_18`, commit `cb3d4ee`) from the official repository into
  `third_party/stockfish`, which is gitignored.
- Any distribution of Stockfish or binaries derived from it must comply with
  GPLv3.

Keeping the fetch step on the participant's machine means the MIT repository
never ships GPLv3 code. Do not vendor Stockfish source into `bench/`,
`tracks/`, or anywhere else under the MIT license, and do not commit
`third_party/`.

To set up and inspect the baseline:

    bash scripts/setup_stockfish.sh
    ceb track-b status

## Track B artifacts: patches against GPLv3 code are GPLv3

A Track B submission is a diff against Stockfish's search files (within the
whitelist enforced by `ceb track-b check-diff`). Implications:

- **Patches are derivative works of Stockfish.** If you distribute a Track B
  patch — or a binary built from patched Stockfish — GPLv3 applies: you must
  license it under GPLv3 and provide corresponding source.
- **Local evaluation is unaffected.** Building and benchmarking a patched
  Stockfish on your own machine, without distributing it, triggers no GPLv3
  distribution obligations.
- **Scores and reports are just data.** Delta-Elo results
  (`ceb.score.track_b/v1`), diff-check output, and run metadata are produced
  by the MIT harness and contain no Stockfish code; they are not derivative
  works and can be shared freely.

If you publish a Track B result, the clean pattern is: share the patch under
GPLv3 (it applies on top of the pinned `sf_18` baseline) and share the JSON
reports under whatever terms you like.

## Submitted engines keep their authors' licenses

Track A submissions are written by participants (or their agents). Running an
engine through the gate, rounds, or leaderboard does **not** relicense it:

- Code you place in a workspace (`runs/<run_id>/workspace/`) remains yours,
  under whatever license you choose. The benchmark only stores evaluation
  outputs about it (reports, game movetext, state).
- The example engines in `examples/submissions/` are part of this repository
  and are MIT like the rest of it.
- If your Track A engine incorporates third-party code (an existing engine,
  GPL move generators, opening data with usage terms), you are responsible
  for complying with those licenses — the harness does not check this.

## Quick reference

| Thing | License | Where |
|---|---|---|
| Harness, oracle, opponents, docs, examples | MIT | `LICENSE` |
| Stockfish baseline (fetched, not shipped) | GPLv3 | `NOTICE`, `third_party/stockfish` |
| Track B patches and patched binaries, when distributed | GPLv3 | derivative of Stockfish |
| Track B/A reports, scores, run metadata | MIT-produced data | `runs/<run_id>/` |
| Track A submitted engines | author's choice | participant workspaces |
