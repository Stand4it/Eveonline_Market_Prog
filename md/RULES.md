# Rules for working with the user
- Every command goes in its own fenced copy block, one command per block. ONE next step at a time. Short answers.
- Script everything possible to save tokens (the `docs`, `status`, `next`, `now` commands exist for that).
- Keep ALL ISK-making on the table, decide by risk-adjusted ISK/hr and ISK per active minute. Stay good: no ganking, red never routed, no botting/macros (CCP rules).
- The user may leave at any moment for 1-9 hours: queue skills, keep the ship docked, list stock; start a trip only if it fits.
- Never `git add -A` on the user's PC (tokens_*.json, profile_*.json live there). Add files by name. Develop only on branch claude/dreamy-edison-n9n32f; no PRs unless asked.
- After any `cli.py` edit run the tests (a bad edit once deleted 22 commands). Commit trailers: Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com> and Claude-Session: https://claude.ai/code/session_01FpAeMd8RZSyQpWh3R9Tigo
- If something looks wrong, say so; do not silently revert the user's changes.
