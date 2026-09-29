#!/bin/bash
# Optional: run the watcher locally as a launchd agent, for an instant desktop
# notification while the Mac is awake. The GitHub Actions workflow covers 24/7
# on its own, so this is a convenience, not the main path.
#
#     bash install_watcher.sh          # install or update
#     bash install_watcher.sh --off    # stop and remove
#
# It installs to ~/Library/Application Support/rolewatch/ rather than running from the repo,
# because macOS privacy protection blocks launchd from touching ~/Desktop and fails silently
# with "Operation not permitted". Re-run this after editing watch_roles.py.
set -euo pipefail

DEST="$HOME/Library/Application Support/rolewatch"
PLIST="$HOME/Library/LaunchAgents/com.rolewatch.agent.plist"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/watch_roles.py"

if [[ "${1:-}" == "--off" ]]; then
  launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "role watcher stopped and removed. State kept at: $DEST"
  exit 0
fi

mkdir -p "$DEST" "$HOME/Library/LaunchAgents"
cp "$SRC" "$DEST/watch_roles.py"

cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.rolewatch.agent</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>$DEST/watch_roles.py</string>
  </array>
  <key>WorkingDirectory</key><string>$DEST</string>
  <key>StartInterval</key><integer>7200</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$DEST/watch.log</string>
  <key>StandardErrorPath</key><string>$DEST/watch.log</string>
</dict>
</plist>
PLISTEOF

if [[ ! -f "$DEST/.roles-seen.json" ]]; then
  echo "no baseline yet - recording what exists now so only CHANGES are reported:"
  /usr/bin/python3 "$DEST/watch_roles.py" --baseline
fi

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo
echo "installed. runs every 2 hours and at login."
echo "  findings:  $DEST/ROLE-WATCH.md"
echo "  run log:   $DEST/watch.log"
echo "  check now: /usr/bin/python3 '$DEST/watch_roles.py'"
echo "  stop:      bash install_watcher.sh --off"
