#!/usr/bin/env bash
# Fetch FinQA at a pinned commit so every benchmark run uses identical data.
set -euo pipefail
COMMIT=0f16e2867befa6840783e58be38c9efb9229d742
DEST=${1:-data/external/FinQA}
if [ ! -d "$DEST/.git" ]; then git clone https://github.com/czyssrs/FinQA.git "$DEST"; fi
git -C "$DEST" fetch --depth 1 origin "$COMMIT" && git -C "$DEST" checkout -q "$COMMIT"
echo "FinQA at $(git -C "$DEST" rev-parse HEAD)"
