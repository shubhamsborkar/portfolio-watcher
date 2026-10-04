@echo off
rem Removes the two scheduled tasks that "Keep Watching.bat" made. Your settings and lists stay.
schtasks /Delete /F /TN "Portfolio watcher morning" >nul 2>nul
schtasks /Delete /F /TN "Portfolio watcher evening" >nul 2>nul
echo The watcher no longer runs on a schedule on this computer. Double-click "Keep Watching.bat" to start it again.
pause
