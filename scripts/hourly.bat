@echo off
rem Hourly refresh of everything the game gives by program: your character (sync), market prices of every region (scan --live) the other grabs (freelance jobs ...) and the names of agents and stations near you (so a station you already read is recognised).
rem `next` / `next --plan` then rank every buy, sell, haul, build and activity from fresh data. Output goes to hourly.log (git-ignored).
rem Set your character below (the one `python -m eve_profit chars` lists).
set EVE_CHAR=Stand4it Dahl
cd /d "%~dp0.."
echo === %date% %time% >> hourly.log
python -m eve_profit sync --char "%EVE_CHAR%" >> hourly.log 2>&1
python -m eve_profit scan --live --max-age 50 --budget 0 --char "%EVE_CHAR%" >> hourly.log 2>&1
python -m eve_profit grabs --char "%EVE_CHAR%" >> hourly.log 2>&1
python -m eve_profit agents --within 6 --char "%EVE_CHAR%" >> hourly.log 2>&1
python -m eve_profit health --char "%EVE_CHAR%" >> health.log 2>&1
