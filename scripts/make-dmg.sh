#!/usr/bin/env bash
#
# Build a drag-to-install disk image: dist/Lustre Reporter.dmg containing
# "Lustre Reporter.app" and an Applications shortcut.
#
# Usage: scripts/make-dmg.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
STAGE="$(mktemp -d)/Lustre Reporter"
mkdir -p "$STAGE"

# Build the self-contained app into the staging area.
bash "$REPO/scripts/make-macos-app.sh" "$STAGE" >/dev/null
ln -s /Applications "$STAGE/Applications"

mkdir -p "$REPO/dist"
DMG="$REPO/dist/Lustre Reporter.dmg"
rm -f "$DMG"
hdiutil create -volname "Lustre Reporter" -srcfolder "$STAGE" \
  -ov -format UDZO "$DMG" >/dev/null
rm -rf "$(dirname "$STAGE")"

echo "Built: $DMG"
echo "Install: open it, then drag \"Lustre Reporter\" onto Applications."
