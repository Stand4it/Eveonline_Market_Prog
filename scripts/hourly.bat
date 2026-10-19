@echo off
rem Hourly refresh of everything the game gives by program: your character (sync), market prices of every region (scan --live) and the other grabs (freelance jobs ...).
rem `next` / `next --plan` then rank every buy, sell, haul, build and activity from fresh data. Output goes to hourly.log (git-ignored).
rem Set your character below (the one `python -m eve_profit chars` lists).
set EVE_CHAR=Stand4it Dahl
cd /d "%~dp0.."
echo === %date% %time% >> hourly.log
python -m eve_profit sync --char "%EVE_CHAR%" >> hourly.log 2>&1
python -m eve_profit scan --live --max-age 50 --char "%EVE_CHAR%" >> hourly.log 2>&1
python -m eve_profit grabs --char "%EVE_CHAR%" >> hourly.log 2>&1
