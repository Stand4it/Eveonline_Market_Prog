# Read first
On EVERY session start, abort or restart: run `git pull`, read `md/START_HERE.md` and `md/STATE.md`, then `python -m eve_profit docs --check`.
Rules for working with this user are in `md/RULES.md` (copy-block commands, one step at a time, script to save tokens, run tests after editing cli.py).
Location (owner 2026-10-21): code, data and databases live on the E drive (`E:\EVE\eveonline`, DBs in `E:\EveProfit`). `C:\Users\Martin Dahl\OneDrive\Documents\EVE\eveonline` is a junction to it, so commands still run from the C path. Put new files, caches and temp output on E, never C temp.
Screenshots go through scripts, not hand edits (owner 2026-10-21, token economy): agent offer -> `python scripts/add_offer.py ...`; AIR career screen -> `python scripts/air_cp.py Enforcer=N Explorer=N Industrialist=N Soldier=N`; any other change -> `python scripts/finish.py "<subject>" "<DECISIONS line>"`. Each does docs + tests + DECISIONS + commit/push in one call. A job done by hand twice becomes a new script here.
After each change: tests, `python -m eve_profit docs`, a line in `md/DECISIONS.md`, commit and push to branch claude/dreamy-edison-n9n32f.
