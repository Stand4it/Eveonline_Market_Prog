# Read first
On EVERY session start, abort or restart: run `git pull`, read `md/START_HERE.md` and `md/STATE.md`, then `python -m eve_profit docs --check`.
Rules for working with this user are in `md/RULES.md` (copy-block commands, one step at a time, script to save tokens, run tests after editing cli.py).
After each change: tests, `python -m eve_profit docs`, a line in `md/DECISIONS.md`, commit and push to branch claude/dreamy-edison-n9n32f.
