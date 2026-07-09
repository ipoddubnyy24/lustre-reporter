#!/usr/bin/env bash
#
# Run Lustre Reporter as a macOS background service (launchd LaunchAgent).
#
#   scripts/daemon.sh start      install (if needed) + start; also autostarts at login
#   scripts/daemon.sh stop       stop the service (agent stays installed)
#   scripts/daemon.sh restart    restart the running service
#   scripts/daemon.sh status     loaded? PID? last exit? port listening?
#   scripts/daemon.sh logs [N]   tail the last N lines of stdout/stderr (default 40)
#   scripts/daemon.sh uninstall  stop and remove the agent (disables login autostart)
#
# Overridable env: LUSTRE_REPORTER_PORT (default 9835), LR_DAEMON_LABEL.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${LUSTRE_REPORTER_PORT:-9835}"
LABEL="${LR_DAEMON_LABEL:-com.ddn.lustre-reporter}"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_OUT="$HOME/Library/Logs/$LABEL.out.log"
LOG_ERR="$HOME/Library/Logs/$LABEL.err.log"
DOMAIN="gui/$(id -u)"
TARGET="$DOMAIN/$LABEL"

write_plist() {
  mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
  cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-c</string>
    <string>export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin; cd "$REPO" &amp;&amp; exec python3 -m lustre_reporter --port $PORT</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>$LOG_OUT</string>
  <key>StandardErrorPath</key><string>$LOG_ERR</string>
</dict>
</plist>
PLIST
}

is_loaded() { launchctl print "$TARGET" >/dev/null 2>&1; }
port_busy() { lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; }

cmd_start() {
  if is_loaded; then
    echo "Service is loaded; restarting to pick up any changes…"
    launchctl kickstart -k "$TARGET" >/dev/null 2>&1 || true
  else
    if port_busy; then
      echo "Refusing to start: port $PORT is already in use (a manual 'run.sh'?)." >&2
      echo "Stop that first, or set LUSTRE_REPORTER_PORT to a free port." >&2
      exit 1
    fi
    write_plist
    launchctl bootstrap "$DOMAIN" "$PLIST" 2>/dev/null || launchctl load -w "$PLIST"
  fi
  _settle
  cmd_status
}

cmd_stop() {
  launchctl bootout "$TARGET" 2>/dev/null || launchctl unload "$PLIST" 2>/dev/null || true
  echo "Stopped $LABEL. (Agent kept at $PLIST — still autostarts at next login; run 'uninstall' to remove.)"
}

cmd_restart() {
  if is_loaded; then
    launchctl kickstart -k "$TARGET" >/dev/null 2>&1 || { cmd_stop; cmd_start; return; }
    _settle
    cmd_status
  else
    cmd_start
  fi
}

cmd_status() {
  echo "Service:  $LABEL"
  echo "Agent:    $([ -f "$PLIST" ] && echo "$PLIST" || echo 'not installed')"
  if is_loaded; then
    local out pid state last
    out="$(launchctl print "$TARGET" 2>/dev/null || true)"
    state="$(printf '%s\n' "$out" | awk -F' = ' '/[[:space:]]state = /{print $2; exit}')"
    pid="$(printf '%s\n' "$out" | awk -F' = ' '/[[:space:]]pid = /{print $2; exit}')"
    last="$(printf '%s\n' "$out" | awk -F' = ' '/last exit code = /{print $2; exit}')"
    echo "Loaded:   yes (state: ${state:-unknown})"
    echo "PID:      ${pid:-none}"
    echo "LastExit: ${last:-n/a}"
  else
    echo "Loaded:   no"
  fi
  if port_busy; then
    echo "Port $PORT: LISTENING  →  https://localhost:$PORT/"
  else
    echo "Port $PORT: not listening"
  fi
  echo "Logs:     $LOG_OUT"
  echo "          $LOG_ERR"
}

cmd_logs() { tail -n "${1:-40}" "$LOG_OUT" "$LOG_ERR" 2>/dev/null || echo "(no logs yet)"; }

cmd_uninstall() {
  launchctl bootout "$TARGET" 2>/dev/null || launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Uninstalled $LABEL (removed $PLIST)."
}

# Give launchd a moment to (re)spawn before we report status.
_settle() { for _ in 1 2 3 4 5 6; do port_busy && break; sleep 0.5; done; }

case "${1:-}" in
  start)     cmd_start ;;
  stop)      cmd_stop ;;
  restart)   cmd_restart ;;
  status)    cmd_status ;;
  logs)      cmd_logs "${2:-40}" ;;
  install)   write_plist; echo "Wrote $PLIST"; cmd_start ;;
  uninstall) cmd_uninstall ;;
  *) echo "usage: $0 {start|stop|restart|status|logs [N]|uninstall}"; exit 2 ;;
esac
