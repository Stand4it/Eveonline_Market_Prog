@echo off
REM Real data, no login needed. Downloads universe (SDE) once, then scans The Forge (change --regions).
cd /d "%~dp0.."
if not exist E:\EveProfit\sde.sqlite python -m eve_profit sde
python -m eve_profit watch --live --regions 10000002
