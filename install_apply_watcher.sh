#!/bin/bash
# Run the APPLY watcher locally as a launchd agent: Snap, Airbnb and Oracle, every 5 minutes,
# any time this Mac is on. Same shape as install_watcher.sh and deliberately a SEPARATE agent,
# so a problem with this one cannot take down the Netflix watcher that sits in front of a
# referral.
#
#     bash install_apply_watcher.sh          # install or update
#     bash install_apply_watcher.sh --off    # stop and remove
#
# Installs to ~/Library/Application Support/rolewatch/ for the reason the sibling installer
# documents: macOS privacy protection blocks launchd from reading ~/Desktop and fails silently
# with "Operation not permitted". Re-run this after editing watch_apply.py OR watch_roles.py,
# because watch_apply imports the matcher from watch_roles and both files are copied.
#
# Every 5 minutes, not 3: three JSON endpoints per pass, one of them Oracle's ~400 KB page.
# launchd runs a StartInterval job on wake if its turn came round while the machine was
# asleep, so closing the lid costs one cycle, not the watch.
set -euo pipefail

DEST="$HOME/Library/Application Support/rolewatch"
PLIST="$HOME/Library/LaunchAgents/com.rolewatch.apply.plist"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${1:-}" == "--off" ]]; then
  launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "apply watcher stopped and removed. State kept at: $DEST"
  exit 0
fi

mkdir -p "$DEST/state" "$HOME/Library/LaunchAgents"
cp "$HERE/watch_apply.py" "$DEST/watch_apply.py"
cp "$HERE/watch_roles.py" "$DEST/watch_roles.py"   # watch_apply imports its matcher

cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.rolewatch.apply</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>$DEST/watch_apply.py</string>
  </array>
  <key>WorkingDirectory</key><string>$DEST</string>
  <key>StartInterval</key><integer>300</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$DEST/apply-watch.log</string>
  <key>StandardErrorPath</key><string>$DEST/apply-watch.log</string>
</dict>
</plist>
PLISTEOF

if [[ ! -f "$DEST/state/apply-seen.json" ]]; then
  echo "no baseline yet - recording what is live now so only NEW reqs fire:"
  /usr/bin/python3 "$DEST/watch_apply.py" --baseline
fi

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo
echo "installed. Snap, Airbnb and Oracle every 5 minutes, and at login."
echo "  queue:     $DEST/state/APPLY-QUEUE.jsonl"
echo "  findings:  $DEST/state/APPLY-WATCH.md"
echo "  run log:   $DEST/apply-watch.log"
echo "  check now: /usr/bin/python3 '$DEST/watch_apply.py'"
echo "  test alert: /usr/bin/python3 '$DEST/watch_apply.py' --test"
echo "  stop:      bash install_apply_watcher.sh --off"
