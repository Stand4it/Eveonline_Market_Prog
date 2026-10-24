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
rem Patch notes + news from CCP's RSS feeds (no login); reads at most once a day, `next` shows a notice when something touches ISK making.
python -m eve_profit.patchnotes >> hourly.log 2>&1
rem Fresh wrecks within 4 jumps (ESI kill counts + the public zKillboard API): salvage leads that expire with the wrecks (2 h).
python -m eve_profit.killleads >> hourly.log 2>&1
rem New static game data from CCP (a patch: agents, items, blueprints)? Checked once a day; reloads the universe when the build changed.
python scripts\sde_refresh.py >> hourly.log 2>&1
