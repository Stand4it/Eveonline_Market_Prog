@echo off
REM Real market data, no login. Needs your real system in profile.json:
REM   python -m eve_profit profile --system "YourSystem" --cargo 5000
cd /d "%~dp0.."
python -m eve_profit universe || exit /b 1
python -m eve_profit watch --live
