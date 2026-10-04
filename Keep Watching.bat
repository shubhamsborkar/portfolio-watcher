@echo off
rem Runs the watcher twice every weekday on this computer, at the two times below (your
rem computer's own clock), using Windows Task Scheduler. No administrator rights are needed:
rem the two tasks belong to your own account. Double-click this file once. "Stop Watching.bat"
rem removes them. Change the times here if your market opens at other hours.
set MORNING=08:30
set EVENING=17:30

cd /d "%~dp0"
if not exist settings.txt (
  echo settings.txt is missing. Copy settings.example.txt to settings.txt, fill in the three lines, and double-click this file again.
  pause
  exit /b 1
)
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install it from python.org ^(the "Install for all users" box stays unticked, so no administrator is needed^), tick "Add python.exe to PATH", then double-click this file again.
  pause
  exit /b 1
)
for /f "delims=" %%p in ('where python') do set PY=%%p& goto found
:found
schtasks /Create /F /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST %MORNING% /TN "Portfolio watcher morning" /TR "\"%PY%\" \"%~dp0watch.py\"" >nul
schtasks /Create /F /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST %EVENING% /TN "Portfolio watcher evening" /TR "\"%PY%\" \"%~dp0watch.py\"" >nul
if errorlevel 1 (
  echo Windows did not accept the scheduled task. Paste this window's text to an AI agent and ask it to fix it.
  pause
  exit /b 1
)
echo The watcher will run every weekday at %MORNING% and %EVENING% on this computer, while it is on.
echo Running it once now, so your phone gets the hello and the map...
"%PY%" "%~dp0watch.py"
pause
