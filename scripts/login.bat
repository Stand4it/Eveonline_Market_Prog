@echo off
REM Needs client_id.txt in the repo folder (or env EVE_CLIENT_ID). Then: login -> sync -> live scan.
cd /d "%~dp0.."
if not exist client_id.txt if "%EVE_CLIENT_ID%"=="" (echo Put your Client ID in client_id.txt & exit /b 1)
if not exist E:\EveProfit\sde.sqlite python -m eve_profit sde || exit /b 1
python -m eve_profit login || exit /b 1
python -m eve_profit sync || exit /b 1
python -m eve_profit scan --live
