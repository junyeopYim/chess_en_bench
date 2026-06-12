#!/usr/bin/env bash
# Public-official strict declaration smoke recipe (v0.3.5).
#
# Builds a SAFE, MOCKED official setup entirely under a temp dir (never the
# repo): a temporary official eval pack, an Ed25519 keypair, a Track B baseline/
# candidate tree, a trusted build wrapper OUTSIDE those trees, a bench-capable
# baseline engine, pinned hashes, and a temp hosted DB. It then runs the strict
# public-official declaration gate (`ceb hosted readiness declare`).
#
# No generated artifact is ever committed (everything lives under $TMP, removed
# on exit). When Docker + the engine/build jail image are available the strict
# declaration can be fully READY; otherwise the gate correctly BLOCKS on the
# jail anchors and we report that full verified e2e requires Docker.
#
# Usage:  bash scripts/public_official_smoke.sh [A|BOTH]   (default: BOTH)
set -euo pipefail

TRACK="${1:-BOTH}"
CEB="${CEB:-ceb}"
PY="${PYTHON:-python3}"
command -v "$CEB" >/dev/null 2>&1 || CEB="$PY -m ceb.cli"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0
ok()   { printf '  [PASS] %s\n' "$1"; PASS=$((PASS+1)); }
bad()  { printf '  [FAIL] %s\n' "$1"; FAIL=$((FAIL+1)); }

echo "public-official smoke — track $TRACK — workdir $TMP"

# --- 1. temp official eval pack (off-repo => not a demo path) ------------------
PACK="$TMP/official_pack"; mkdir -p "$PACK"
TINY="$(cd "$(dirname "$0")/.." && pwd)/examples/eval_packs/tiny_private"
cp "$TINY/fen_hidden.jsonl" "$TINY/perft_hidden.jsonl" \
   "$TINY/openings_hidden.jsonl" "$PACK/"
cat > "$PACK/manifest.json" <<'JSON'
{
  "schema": "ceb.eval_pack.manifest/v1",
  "pack_id": "ceb-smoke-2026s1",
  "name": "Smoke Official Pack",
  "track": "both",
  "season": "2026-s1",
  "official": true,
  "visibility": "private",
  "openings_mode": "replace"
}
JSON

# --- 2. Ed25519 keypair --------------------------------------------------------
$CEB hosted keygen --private-key "$TMP/op.pem" --public-key "$TMP/op.pub.pem" \
  >/dev/null

# --- 3. Track B baseline/candidate trees + trusted wrapper (outside trees) -----
BASE="$TMP/baseline"; CAND="$TMP/candidate"
mkdir -p "$BASE/src" "$CAND/src"
printf 'int margin = 1;\n' > "$BASE/src/search.cpp"
printf 'int margin = 2;\n' > "$CAND/src/search.cpp"
WRAPPER="$TMP/trusted_wrapper.sh"            # OUTSIDE both trees
cat > "$WRAPPER" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
SRC="$1"; OUT="$2"; ENGINE="$3"
cp -a "$SRC"/. "$OUT"/
printf '#!/bin/sh\n' > "$ENGINE"; chmod +x "$ENGINE"
SH
chmod +x "$WRAPPER"

# --- 4. bench-capable baseline engine (stands in for built pinned Stockfish) ---
BENCH_ENGINE="$TMP/sf_bench.sh"
cat > "$BENCH_ENGINE" <<'SH'
#!/bin/sh
while read line; do
  case "$line" in
    bench) echo 'Nodes searched  : 1000000'; echo 'Nodes/second    : 2000000';;
    quit) exit 0;;
  esac
done
SH
chmod +x "$BENCH_ENGINE"

# --- 5. pinned hashes (computed from the installed package) --------------------
PACK_HASH="$($PY -c "from ceb.hosted.eval_pack_trust import compute_eval_pack_hash as h; print(h('$PACK'))")"
WRAP_HASH="$($PY -c "from ceb.hosted.build_wrappers import compute_wrapper_hash as h; print(h('$WRAPPER'))")"
BASE_HASH="$($PY -c "from ceb.hosted.metadata import source_tree_hash as h; print(h('$BASE'))")"

# --- 6. temp hosted DB + release manifest -------------------------------------
DB="$TMP/hosted.sqlite"
$CEB hosted init --db "$DB" >/dev/null
REL="$TMP/release.json"
REL_TRACK="A"; [ "$TRACK" = "BOTH" ] && REL_TRACK="B"
if [ "$REL_TRACK" = "B" ]; then
  $CEB hosted release-manifest create --track B --eval-pack "$PACK" \
    --public-key "$TMP/op.pub.pem" --official-pack-hash "$PACK_HASH" \
    --track-b-baseline-hash "$BASE_HASH" --build-wrapper-hash "$WRAP_HASH" \
    --private-key "$TMP/op.pem" --out "$REL" >/dev/null || true
else
  $CEB hosted release-manifest create --track A --eval-pack "$PACK" \
    --public-key "$TMP/op.pub.pem" --official-pack-hash "$PACK_HASH" \
    --private-key "$TMP/op.pem" --out "$REL" >/dev/null || true
fi
[ -f "$REL" ] && ok "signed release manifest created" || bad "release manifest"

# Verify the signed manifest is authentic only with the out-of-band public key.
if [ -f "$REL" ]; then
  $CEB hosted release-manifest verify --manifest "$REL" \
    --public-key "$TMP/op.pub.pem" >/dev/null \
    && ok "release manifest authentic with public key" \
    || bad "release manifest verify"
  $CEB hosted release-manifest verify --manifest "$REL" >/dev/null 2>&1 \
    && bad "unsigned-trust check (should NOT be authentic without key)" \
    || ok "release manifest NOT authentic without out-of-band key"
fi

# --- 7. negative: the committed demo pack can NEVER declare ready --------------
if $CEB hosted readiness declare --db "$DB" --eval-pack "$TINY" \
     --public-key "$TMP/op.pub.pem" --signing-key "$TMP/op.pem" \
     --track A --json >/dev/null 2>&1; then
  bad "demo pack declared ready (must be blocked)"
else
  ok "demo pack correctly NOT declarable"
fi

# --- 8. strict declaration with the mocked official assets --------------------
declare_args=(hosted readiness declare --db "$DB" --eval-pack "$PACK"
  --public-key "$TMP/op.pub.pem" --signing-key "$TMP/op.pem"
  --official-pack-hash "$PACK_HASH" --release-manifest "$REL" --track "$TRACK")
if [ "$TRACK" = "BOTH" ]; then
  declare_args+=(--build-wrapper "$WRAPPER" --build-wrapper-hash "$WRAP_HASH"
    --baseline-src "$BASE" --track-b-baseline-hash "$BASE_HASH"
    --track-b-baseline-engine "$BENCH_ENGINE")
fi

DOCKER_OK=0
if command -v docker >/dev/null 2>&1 && \
   docker image inspect chess-en-bench-jail:0.4 >/dev/null 2>&1; then
  DOCKER_OK=1
fi

REPORT="$TMP/readiness.json"
set +e
$CEB "${declare_args[@]}" --json > "$REPORT" 2>/dev/null
RC=$?
set -e

if [ "$DOCKER_OK" = "1" ]; then
  if [ "$RC" = "0" ]; then
    ok "strict declaration READY (track $TRACK, real jail path)"
  else
    bad "strict declaration not ready despite Docker + jail image"
    $PY -c "import json;d=json.load(open('$REPORT'));print('   blocking:',d.get('blocking_failures'))" 2>/dev/null || true
  fi
else
  echo "  [note] Docker / jail image absent: full verified e2e requires Docker."
  if [ "$RC" != "0" ]; then
    ok "strict declaration correctly BLOCKS without Docker (jail anchors)"
  else
    bad "strict declaration unexpectedly ready without Docker"
  fi
fi

# --- 9. render a commit-safe checklist from the declaration -------------------
if [ -s "$REPORT" ]; then
  $CEB hosted release-checklist create --track "$TRACK" \
    --readiness-report "$REPORT" --release-manifest "$REL" \
    --out "$TMP/CHECKLIST.md" >/dev/null \
    && ok "release checklist rendered" || bad "release checklist"
fi

echo "----------------------------------------"
echo "public-official smoke: $PASS passed, $FAIL failed"
[ "$FAIL" = "0" ] && { echo "RESULT: PASS"; exit 0; } || { echo "RESULT: FAIL"; exit 1; }
