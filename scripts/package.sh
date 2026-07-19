#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RELEASE_DIR="$(dirname "$ROOT")"
ZIP_OUT="$RELEASE_DIR/harborvision-twin-v2.0.0.zip"
BUNDLE_OUT="$RELEASE_DIR/harborvision-twin-v2.0.0.bundle"
CHECKSUM_OUT="$RELEASE_DIR/harborvision-twin-v2.0.0.sha256"

rm -f "$ZIP_OUT" "$BUNDLE_OUT" "$CHECKSUM_OUT"
cd "$RELEASE_DIR"
zip -qr "$ZIP_OUT" "$(basename "$ROOT")" \
  -x '*/__pycache__/*' '*/.pytest_cache/*' '*/.mypy_cache/*' '*/.ruff_cache/*' \
     '*/.git/*' '*/.venv/*' '*/node_modules/*' '*/harborvision.db' '*/data/generated/*'

git -C "$ROOT" bundle create "$BUNDLE_OUT" --all
sha256sum "$ZIP_OUT" "$BUNDLE_OUT" > "$CHECKSUM_OUT"
printf '%s\n%s\n%s\n' "$ZIP_OUT" "$BUNDLE_OUT" "$CHECKSUM_OUT"
