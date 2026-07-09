#!/usr/bin/env bash
#
# Build a self-contained "Lustre Reporter.app" that runs independently of the
# source tree (the Python code + web assets are copied into the bundle). Install
# it by dropping it in /Applications. It stores its TLS cert and local config
# under ~/Library/Application Support/Lustre Reporter (the bundle stays
# read-only). Data still comes from the llm_jira CLIs (jira/gerrit/maloo) on PATH.
#
# Usage: scripts/make-macos-app.sh [install-dir]   (default: ~/Applications)
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_DIR="${1:-$HOME/Applications}"
APP="$INSTALL_DIR/Lustre Reporter.app"

echo "Building self-contained app: $APP"
mkdir -p "$INSTALL_DIR"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# Bundle the application code + web assets so it needs no source checkout.
cp -R "$REPO/lustre_reporter" "$APP/Contents/Resources/lustre_reporter"
cp -R "$REPO/static" "$APP/Contents/Resources/static"
find "$APP/Contents/Resources" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$APP/Contents/Resources" -name '*.pyc' -delete 2>/dev/null || true

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Lustre Reporter</string>
  <key>CFBundleDisplayName</key><string>Lustre Reporter</string>
  <key>CFBundleIdentifier</key><string>com.ddn.lustre-reporter</string>
  <key>CFBundleVersion</key><string>0.1.0</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>lustre-reporter</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>LSMinimumSystemVersion</key><string>10.13</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSHumanReadableCopyright</key><string>(c) 2026 Ivan Poddubnyy - Apache-2.0</string>
</dict>
</plist>
PLIST

# App icon (best-effort — a missing icon just falls back to the generic one).
if command -v iconutil >/dev/null 2>&1; then
  SET="$(mktemp -d)/AppIcon.iconset"
  mkdir -p "$SET"
  if python3 "$REPO/scripts/gen_icon.py" "$SET" >/dev/null; then
    iconutil -c icns "$SET" -o "$APP/Contents/Resources/icon.icns" \
      || echo "warning: iconutil failed; using default icon"
  fi
  rm -rf "$(dirname "$SET")"
else
  echo "warning: iconutil not found; using default icon"
fi

# Launcher: run the bundled server, keep writable state in Application Support.
cat > "$APP/Contents/MacOS/lustre-reporter" <<'LAUNCH'
#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
RES="$(cd "$(dirname "$0")/../Resources" && pwd)"
SUPPORT="$HOME/Library/Application Support/Lustre Reporter"
mkdir -p "$SUPPORT/certs"
export PYTHONPATH="$RES"
export LUSTRE_REPORTER_CERT_DIR="$SUPPORT/certs"
export LUSTRE_REPORTER_CONFIG="$SUPPORT/config.local.json"
LOG="$SUPPORT/lustre-reporter.log"
PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
  osascript -e 'display alert "Lustre Reporter" message "python3 was not found. Install the Xcode Command Line Tools (run: xcode-select --install) or Homebrew Python, then open Lustre Reporter again."' >/dev/null 2>&1
  exit 1
fi
exec "$PY" -m lustre_reporter --port 9835 --open >>"$LOG" 2>&1
LAUNCH
chmod +x "$APP/Contents/MacOS/lustre-reporter"

# Refresh Launch Services so the name/icon show immediately.
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
  -f "$APP" >/dev/null 2>&1 || true

echo
echo "Built: $APP"
echo "Run it: open \"$APP\"   (opens https://localhost:9835; quit from the Dock)"
echo "Autostart: System Settings -> General -> Login Items -> '+' -> \"Lustre Reporter\""
echo "Note: data needs the llm_jira CLIs (jira/gerrit/maloo) installed on PATH."
