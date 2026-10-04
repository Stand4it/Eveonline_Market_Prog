@echo off
REM One-time setup: DB on E:, profile, test, mock demo.
cd /d %~dp0..
if not exist E:\EveProfit mkdir E:\EveProfit
python -m eve_profit init
if not exist profile.json python -m eve_profit profile
python -m unittest discover -s tests
python -m eve_profit mock
python -m eve_profit scan
echo Edit profile.json (ship, cargo, system), then run scripts\watch_mock.bat or scripts\go_live.bat
