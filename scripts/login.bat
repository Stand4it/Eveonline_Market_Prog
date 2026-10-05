@echo off
REM Usage: set EVE_CLIENT_ID=<your app client id>  then run scripts\login.bat
cd /d "%~dp0.."
if "%EVE_CLIENT_ID%"=="" (echo Set EVE_CLIENT_ID first, see README & exit /b 1)
if not exist E:\EveProfit\sde.sqlite python -m eve_profit sde
python -m eve_profit login && python -m eve_profit sync && python -m eve_profit scan --live
