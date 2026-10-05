@echo off
REM One-time setup. Mock demo uses its OWN database so your real data stays clean.
cd /d "%~dp0.."
if not exist E:\EveProfit mkdir E:\EveProfit
python -m eve_profit init || exit /b 1
if not exist profile.json python -m eve_profit profile
python -W ignore -m unittest discover -s tests 2>&1 | findstr /R "Ran OK FAIL ERROR"
python -m eve_profit mock --db E:\EveProfit\mock.db
python -m eve_profit scan --db E:\EveProfit\mock.db
