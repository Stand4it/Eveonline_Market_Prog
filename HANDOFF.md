# HANDOFF - read this first after any restart or context loss

Repo `stand4it/eveonline_market_prog`, branch `claude/dreamy-edison-n9n32f` (never push elsewhere; no PRs unless asked).
Pure-stdlib Python 3 (user's PC: Windows, Python 3.13, PowerShell). 155 tests: `python -m unittest discover -s tests`.
The cloud sandbox cannot reach ESI/zKill/most sites; only the user's PC runs live commands and pastes output back.
Database `E:\EveProfit\eve_profit[_label].db`, profiles `profile[_label].json`, logins `tokens[_label].json` (all git-ignored).

## How to work with this user (standing rules)
- Put EVERY command in its own fenced copy block, one command per block; give ONE next step at a time; short answers.
- Script as much as possible to save tokens. After editing `cli.py` ALWAYS run the tests (`tests/test_cli_dispatch.py` catches
  a command losing its branch - a bad edit once deleted 22 branches).
- Keep ALL ISK-making on the table; decide by risk-adjusted ISK/hr (and per active minute); stay good (no ganking, red never routed,
  no botting/macroing - CCP rules); the user may have to leave at a moment's notice for 1-9 hours (queue skills, keep ship docked,
  list stock, only start a trip that fits).
- Do not revert/undo what the user changes; if something looks wrong, say so. Commit trailers: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`
  and `Claude-Session: https://claude.ai/code/session_01FpAeMd8RZSyQpWh3R9Tigo`.

## Characters (auto-picked: the one that is ONLINE; else last used; `--char NAME` overrides)
- Stand Dahldaberg (main, label "" / tokens.json): Mammoth hauler, Hek. Stock listed/held (Filaments etc.), trading skills at V.
- Stand Dahldaberg02 (label `fresh`): Tayra, ~15M ISK. Stand Dahldaberg3: further along; not synced into the tool yet.
- Stand4it Dahl: NEW Gallente character (experiment: start from scratch with the tool). Velator; docked Rotonos IV (Center for
  Advanced Studies, AIR career corp). Doing AIR Career Program, path Soldier of Fortune, agent Arabeton Spilmottin (L1).
  Plan: time each mission with start/stop, learn real ISK/hr per activity and ship, then let the tool pick the best career.
- Client ID is in `client_id.txt` (32 hex, 1bcbf467858d46c29b98c19f5cf383c7; looked up in cwd, repo root, scripts/); callback port 8801.

## Commands (run from the repo folder, `python -m eve_profit <cmd>`)
now [--fast] (sync+scan+next step+worldwide price check) | next | stock | sellplan | day --hours 8 | compare --to Jita |
journey --to Jita [--live] [--quick] [--detour N] | bestprice --item NAME_OR_ID [--qty N] | check --pick N | go --pick N [--send] [--away] |
scan [--live] [--away] [--max-age 15] | skills --hours 72 | trainplan --hours 24 | start --activity NAME | stop [--isk N] [--paused MIN] [--no-loot] |
activities | status (where everything is stored, row counts, PowerShell history path) | log --activity N --isk X --hours H | combatfit --dps --ehp --tank --value [--ship] | chars | login | sync | fleet | fit | zkill |
along --to X | keep | bpbuy | update | universe | diag.

## Agent missions (built in a separate session on the user's PC; merged here from branch `agent-missions-local`)
- `scripts/agent_steps.py [next|list|done|skip|back|reset]`: Level-1 agent checklist (never touches timers; copies the START command to the clipboard).
  State `scripts/agent_steps_state.json`; DB path inside is `E:/EveProfit/eve_profit_dahl.db` (character Stand4it Dahl).
- `agent_offers.json`: the open L1 agent offers, entered from screenshots (isk, bonus, taxed?, loot, cost, task_min, jumps, available).
  Edit it after each new screenshot; `next` ranks offers by NET ISK/hr incl. travel ("BEST AGENT OFFERS RIGHT NOW").
- Timed runs named `Agent L1 ...` feed "AGENT MISSIONS (measured)"; when >= 1.2x the best trade, `next` says DO AGENT MISSIONS FIRST.
- `pause` / `resume` freeze the `start` timer (no login needed); `stop --paused N` also works. Measured so far: ~0.95-1.0M ISK/hr
  for L1 agent steps vs ~147k ISK/hr best trade. NOTE: `stop` shows 0 ISK if run before the wallet journal updates (wait ~2 min).
- Repo moved: GitHub now redirects to `Stand4it/Eveonline_Market_Prog` (owner capitalised); the old URL still works.
- NEVER `git add -A` on the user's PC: tokens_*.json / profile_*.json live there (now in .gitignore).

## Key behaviours/assumptions
- Sales tax = 7.5% x (1 - 0.11 x Accounting); broker fee = 3% - 0.3% x Broker Relations (verify in the sell window). Listing must beat
  instant sale by >15% and >=250k; order slots = 5+4 Trade+8 Retail+16 Wholesale+32 Tycoon.
- `--live` skips regions fetched < `--max-age` min ago and saves each region as it arrives (Ctrl+C is safe). First scan of a new
  character DB is slow (10-25 min).
- `stop` counts wallet-journal payouts (bounties, mission reward + time bonus, discovery, insurance) PLUS loot valued at the best
  market net of round-trip travel time at 6M ISK/hr (hours include that trip). Loot must be in a station hangar (not ship cargo).
- Home-station task: if home is a player structure, `now`/`next` tell the user to set an NPC station home (needs clones scope; re-login).
- ESI cannot move the ship, start autopilot or undock; it only sets waypoints.

## Not yet verified on live data
journey, compare, loot valuation in stop, stop reading the real wallet journal, home-station read, trainplan on a real character.

## Next ideas (user-agreed direction)
career-agent activities in the planner; scale measured L1 results to higher levels by ship+skill points; training suggestions that
improve the model; patient buy orders for away time; auto hangar snapshot; reprocess-or-sell; ship shopping advisor; multi-leg `go`
(user said current `go` already does buy station then sell station, so left as is); eve-trading.net / evemarketbrowser.com are
blocked from the sandbox (user can paste numbers to cross-check; item pages use type IDs, `bestprice --item <id>` works).
