#!/usr/bin/env bash
# Fetch the pinned Track B Stockfish baseline into third_party/stockfish.
# Pin source of truth: tracks/b_stockfish_opt/stockfish.lock
# (Stockfish 18, tag sf_18, commit cb3d4ee). Never a moving branch.
set -euo pipefail
cd "$(dirname "$0")/.."

REPO="https://github.com/official-stockfish/Stockfish.git"
TAG="sf_18"
PINNED_COMMIT="cb3d4ee"
DEST="third_party/stockfish"

mkdir -p third_party
if [ ! -d "$DEST/.git" ]; then
    echo "cloning $REPO into $DEST ..."
    git clone "$REPO" "$DEST"
else
    echo "$DEST already exists; fetching tags ..."
    git -C "$DEST" fetch --tags origin
fi

git -C "$DEST" checkout "$TAG"

HEAD="$(git -C "$DEST" rev-parse HEAD)"
case "$HEAD" in
    "$PINNED_COMMIT"*)
        echo "checked out $TAG at $HEAD (matches pinned commit $PINNED_COMMIT)"
        ;;
    *)
        echo "ERROR: HEAD $HEAD does not match pinned commit $PINNED_COMMIT" >&2
        echo "Refusing to continue; check tracks/b_stockfish_opt/stockfish.lock" >&2
        exit 1
        ;;
esac

echo
echo "Next steps:"
echo "  ceb track-b status"
echo "  cd $DEST/src && make -j build    # requires make + a C++17 compiler"
