@echo off
REM Real market data, no login. Needs your real system in profile.json:
REM   python -m eve_profit profile --system "YourSystem" --cargo 5000
cd /d "%~dp0.."
if not exist E:\EveProfit\sde.sqlite python -m eve_profit sde || exit /b 1
python -m eve_profit watch --live
