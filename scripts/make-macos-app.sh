#!/usr/bin/env bash
#
# Build "Lustre Reporter.app" so it is clearly identifiable in macOS
# System Settings → General → Login Items (shows the name + custom icon).
#
# Usage: scripts/make-macos-app.sh [install-dir]   (default: ~/Applications)
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_DIR="${1:-$HOME/Applications}"
APP="$INSTALL_DIR/Lustre Reporter.app"
PY="$(command -v python3 || true)"
[ -n "$PY" ] || { echo "python3 not found on PATH" >&2; exit 1; }

echo "Building $APP"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

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
  <key>LSUIElement</key><true/>
  <key>LSMinimumSystemVersion</key><string>10.13</string>
  <key>NSHumanReadableCopyright</key><string>(c) 2026 Ivan Poddubnyy - Apache-2.0</string>
</dict>
</plist>
PLIST

# App icon (best-effort — a missing icon just falls back to the generic one).
if command -v iconutil >/dev/null 2>&1; then
  SET="$(mktemp -d)/AppIcon.iconset"
  mkdir -p "$SET"
  if "$PY" "$REPO/scripts/gen_icon.py" "$SET" >/dev/null; then
    iconutil -c icns "$SET" -o "$APP/Contents/Resources/icon.icns" \
      || echo "warning: iconutil failed; using default icon"
  fi
  rm -rf "$(dirname "$SET")"
else
  echo "warning: iconutil not found; using default icon"
fi

# Launcher: start the HTTPS server and open the dashboard.
cat > "$APP/Contents/MacOS/lustre-reporter" <<EOF
#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:\$PATH"
cd "$REPO"
exec "$PY" -m lustre_reporter --port 9835 --open
EOF
chmod +x "$APP/Contents/MacOS/lustre-reporter"

# Refresh Launch Services so the name/icon show immediately.
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
  -f "$APP" >/dev/null 2>&1 || true

echo
echo "Built: $APP"
echo "Add to autostart:  System Settings -> General -> Login Items -> '+' -> \"Lustre Reporter\""
echo "It will appear there by name with the bar-chart icon, and open https://localhost:9835 at login."
