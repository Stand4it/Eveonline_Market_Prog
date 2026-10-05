@echo off
REM Usage:  scripts\first_run.bat "Your System Name" [cargo_m3]     (stops at first failure)
cd /d "%~dp0.."
echo [1/4] Checking Python...
python --version >nul 2>&1 || (echo Python not found. Install 3.11+ from python.org ^(tick "Add to PATH"^) and rerun. & exit /b 1)
python -c "import sys; sys.exit(0 if sys.version_info>=(3,11) else 1)" || (echo Python is older than 3.11. Please upgrade. & exit /b 1)
python --version
echo [2/4] Setup, universe download, live market scan...
call scripts\setup.bat || exit /b 1
if "%~1"=="" (echo Give your system name:  scripts\first_run.bat "Jita" 5000 & exit /b 1)
python -m eve_profit profile --system "%~1" --cargo %~2 || exit /b 1
if not exist E:\EveProfit\sde.sqlite python -m eve_profit sde || exit /b 1
python -m eve_profit scan --live || (echo Live scan failed - send me this output. & exit /b 1)
echo [3/4] EVE login...
if "%EVE_CLIENT_ID%"=="" (echo Live scan OK. To continue: create the app at developers.eveonline.com, run  set EVE_CLIENT_ID=your_id  then rerun this file. & exit /b 0)
python -m eve_profit login || exit /b 1
python -m eve_profit sync || exit /b 1
echo [4/4] Edit profile.json: ship_ehp, ship_tank_dps, ship_value_isk, mining_yield_m3_s, minable_ores, combat_dps.
python -m eve_profit scan --live
