#!/bin/bash
# Runs the watcher twice every weekday on this Mac, at the two times below (the Mac's own clock),
# through launchd, the Mac's own scheduler. No administrator password is needed: the entry belongs
# to your own account. Double-click this file once. "Stop Watching.command" removes it. If the Mac
# was asleep at the time, launchd runs it when the Mac wakes.
MORNING_H=8;  MORNING_M=30
EVENING_H=17; EVENING_M=30

cd "$(dirname "$0")"
if [ ! -f settings.txt ]; then
  echo "settings.txt is missing. Copy settings.example.txt to settings.txt, fill in the three lines, and double-click this file again."
  read -r -p "Press Enter to close."; exit 1
fi
PY=$(command -v python3)
if [ -z "$PY" ]; then
  echo "Python was not found. Install it from python.org, then double-click this file again."
  read -r -p "Press Enter to close."; exit 1
fi
PLIST="$HOME/Library/LaunchAgents/com.portfolio-watcher.plist"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.portfolio-watcher</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>$PWD/watch.py</string></array>
  <key>WorkingDirectory</key><string>$PWD</string>
  <key>StartCalendarInterval</key><array>
$(for d in 1 2 3 4 5; do
  echo "    <dict><key>Weekday</key><integer>$d</integer><key>Hour</key><integer>$MORNING_H</integer><key>Minute</key><integer>$MORNING_M</integer></dict>"
  echo "    <dict><key>Weekday</key><integer>$d</integer><key>Hour</key><integer>$EVENING_H</integer><key>Minute</key><integer>$EVENING_M</integer></dict>"
done)
  </array>
  <key>StandardOutPath</key><string>$PWD/last-run.log</string>
  <key>StandardErrorPath</key><string>$PWD/last-run.log</string>
</dict></plist>
EOF
launchctl unload "$PLIST" 2>/dev/null
launchctl load "$PLIST"
echo "The watcher will run every weekday at $MORNING_H:$(printf %02d $MORNING_M) and $EVENING_H:$(printf %02d $EVENING_M) on this Mac. Each run's output is in last-run.log."
echo "Running it once now, so your phone gets the hello and the map..."
"$PY" watch.py
read -r -p "Press Enter to close."
