# Forbidden behaviors (normative)

This list applies to every evaluated agent and to everything it submits
(engine binaries, sources, `build.sh`, Track B patches). "MUST NOT" is
normative. Violating any rule invalidates the affected evaluation: a gate
attempt fails, or an official/quick round is invalidated and — for official
rounds — still consumes round budget. Deliberate or repeated violations
invalidate the entire run.

Where the benchmark already enforces a rule mechanically, the enforcement point is
named. Everything else is enforced by operator review of the workspace and
artifacts; "not detected automatically" never means "allowed".

## Both tracks

1. **No network access at run time.** Submissions MUST NOT open network
   connections during build (`build.sh`), the gate, or any match — no
   downloads, no online engines or tablebases, no telemetry.
   *(Enforced when evaluations run with `--sandbox docker` (`--network none`);
   the default host mode does not block it — see docs/security.md.)*

2. **No reading or patching benchmark internals or opponents.** Submissions
   MUST NOT read, import, modify, or link against `bench/ceb/` (including
   the oracle in `bench/ceb/chess/` and the opponents in
   `bench/ceb/match/opponents.py`), `tracks/*/private/`, or other runs'
   data. Public track data (`tracks/*/public/`, configs marked public) is
   readable by design.

3. **No writing outside the workspace.** All files a submission creates or
   modifies MUST stay inside its own workspace directory
   (`runs/<run-id>/workspace/`, created by `ceb workspace prepare`).

4. **No targeting the harness process or files.** Submissions MUST NOT
   signal, kill, ptrace, or otherwise interfere with the harness or sibling
   processes, and MUST NOT tamper with `runs/`, `artifacts/`, reports, or
   PGN/game files. *(Enforced: engines run in their own process group and are
   killed as a group on close — `bench/ceb/uci/client.py`.)*

5. **No output flooding or protocol abuse.** Engines MUST NOT spam stdout to
   stall evaluation, and MUST answer UCI commands within the configured
   timeouts. *(Enforced: lines are truncated at 8,192 chars, intake is capped at
   10,000 queued lines, stderr is discarded, and every read times out —
   flooding hurts only the engine, and timeouts are scored as faults with
   penalties per `tracks/a_from_scratch/scoring.yaml`.)*

6. **No illegal moves.** Every move is validated against the internal
   oracle; illegal moves are faults and are penalized.
   *(Enforced — `bench/ceb/match/internal_runner.py`.)*

## Track A (from-scratch engine)

7. **No external chess libraries or engines.** The engine MUST be built
   from scratch: no `python-chess`, no Stockfish/Lc0 (binaries, sources, or
   NNUE weights), no move-generation or search libraries, no opening books
   or tablebases. Generic non-chess libraries (stdlib, build tooling) are
   fine. Vendoring or transcribing an existing engine's code counts as
   using it.

8. **No precomputed answers to public test data.** Hard-coding bestmoves
   for `tracks/a_from_scratch/public/fen_examples.jsonl` or perft counts
   for `perft_examples.jsonl` instead of computing them is a violation.

## Track B (Stockfish search optimization)

9. **No moving-branch baselines.** The baseline MUST be exactly the pin in
   `tracks/b_stockfish_opt/stockfish.lock` (Stockfish 18, tag `sf_18`,
   commit `cb3d4ee`), fetched via `scripts/setup_stockfish.sh` — never
   `master` or any other moving ref. Results against any other baseline are
   invalid. *(Enforced: the setup script refuses a HEAD that does not match the
   pinned commit.)*

10. **No edits outside the diff whitelist.** Candidates may differ from the
    baseline only in files matching `tracks/b_stockfish_opt/allowed_paths.txt`
    (search/movepick/history/timeman/tt). Files matching
    `forbidden_paths.txt` (evaluation, NNUE, movegen, position, bitboards,
    UCI, Makefiles, scripts) MUST NOT change even if a whitelist edit ever
    overlapped — forbidden wins. No files may be added or removed
    (`patch_policy.yaml`). *(Enforced — run it yourself:)*

    ```sh
    ceb track-b check-diff --baseline third_party/stockfish --candidate <dir>
    ```

11. **The candidate must remain a complete Stockfish.** It MUST build with
    the unmodified Makefile and pass the baseline `bench` command; gutting
    evaluation through whitelisted files is a violation of intent even when
    the diff check passes.

## Consequences

- Gate phase (Track A): violation = failed gate attempt. Attempts are
  unlimited, so fix and rerun: `ceb gate run --track A --workspace <dir>`.
- Rounds: violation = the round is invalidated and excluded from the final
  score (final score is the best **valid** round); an invalidated official
  round still spends one of the 3 official-round slots.
- Track B: a failed `check-diff` or wrong baseline makes the candidate
  ineligible for scoring.
- Faults that are violations of timing or legality (illegal_move, timeout,
  crash) additionally carry per-fault score penalties (30/15/25 points).
