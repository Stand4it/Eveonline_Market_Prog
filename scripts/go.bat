@echo off
REM scripts\go.bat [N]  -> sets in-game waypoints for ranked opportunity N (default 1). Dry run: omit --send.
cd /d "%~dp0.."
python -m eve_profit go --send --pick %~1
