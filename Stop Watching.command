#!/bin/bash
# Removes the launchd entry that "Keep Watching.command" made. Your settings and lists stay.
PLIST="$HOME/Library/LaunchAgents/com.portfolio-watcher.plist"
launchctl unload "$PLIST" 2>/dev/null
rm -f "$PLIST"
echo "The watcher no longer runs on a schedule on this Mac. Double-click \"Keep Watching.command\" to start it again."
read -r -p "Press Enter to close."
