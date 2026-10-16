#!/bin/bash
# Run the watcher locally as a launchd agent: a desktop notification within three minutes
# of a req going live, any time this Mac is on. launchd runs a StartInterval job on wake if
# its turn came round while the machine was asleep, so closing the lid costs one cycle, not
# the watch.
#
# Netflix every 3 minutes, Meta every 10 (its sitemap is ~1 MB; Netflix's API is a few KB).
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
    <string>--meta-every</string><string>10</string>
  </array>
  <key>WorkingDirectory</key><string>$DEST</string>
  <key>StartInterval</key><integer>180</integer>
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
echo "installed. Netflix every 3 minutes, Meta every 10, and at login."
echo "  findings:  $DEST/ROLE-WATCH.md"
echo "  run log:   $DEST/watch.log"
echo "  check now: /usr/bin/python3 '$DEST/watch_roles.py'"
echo "  test the alert: /usr/bin/python3 '$DEST/watch_roles.py' --test"
echo "  stop:      bash install_watcher.sh --off"
