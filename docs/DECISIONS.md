# Decisions

- 2026-06-12 — Core package is stdlib-only (FastAPI/uvicorn as optional `server` extra) — keeps the gate/runner installable anywhere and enforces "from scratch" credibility.
- 2026-06-12 — Oracle uses copy-make legality filtering over (file,rank)-delta movegen — slower than bitboards but simple to audit; correctness proven by canonical perft counts in tests.
- 2026-06-12 — `go perft` UCI extension is recommended (warn), not mandatory (fail) in the gate — lets minimal engines pass while still verifying counts when present.
- 2026-06-12 — Quick rounds are free; only official rounds consume the 3-round budget — gives agents a cheap end-to-end smoke path.
- 2026-06-12 — Track B pinned to Stockfish 18 / sf_18 / cb3d4ee in stockfish.lock; sources fetched to gitignored third_party/ — never a moving branch, no GPLv3 code in-repo.
- 2026-06-12 — Configs use a documented YAML subset parsed by ceb.config — avoids a pyyaml dependency for trivially flat files.
- 2026-06-12 — Match artifacts use UCI movetext in PGN-style wrappers, not SAN — SAN disambiguation complexity isn't worth it for v0.1; JSON is the machine record.
