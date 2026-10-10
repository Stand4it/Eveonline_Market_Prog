# Roadmap (stages)

| Stage | Scope | Needs EVE login? | Status |
|---|---|---|---|
| 1 | SQLite DB (E:\EveProfit), universe graph, red-avoid/yellow-penalty routing, hauling-trade + inventory-liquidation + mining ranking by ISK/hr & ISK/jump, mock data, tests | No | **Done** |
| 2 | Live public data: SDE universe import, ESI regional orders, kill-feed risk, continuous `watch` scanning, long-haul ranges | No (public ESI; run on your PC) | Code written, **unverified** (sandbox blocks ESI) |
| 3 | EVE SSO (PKCE) login + `sync`: location, ship, cargo, skills, wallet, assets, LP, standings; player-structure markets | **Yes** | Code + tests done; live login unverified |
| 4 | Manufacturing + contracts + skill and job-slot checks (blueprint/ore skills, BPC runs, Mass Production slots, running jobs) | Yes | Done |
| 5 | NPC combat + own-wreck salvage + mission agents (standing gate, LP value) + LP-store redemption | Optional | Done (payout numbers are placeholders) |
| 6 | Route automation: ESI waypoints at every safe-path system, dry-run default, red refusal, hot-system alerts in watch | Yes | Done; live waypoint call unverified |

Ground rules: no suicide-ganking/ninja-looting by default; red systems never routed; yellow penalised.
CCP rules: ESI cannot move your ship; it can only set waypoints. Automating in-game input is not allowed.

| 7 | Ship shopping advisor, journey composer, character contracts, multi-character, reactions/T2/PI | Yes | Planned (see STATUS.md backlog) |


## THE VISION (user, 2026-10-10): a comprehensive EVE player-development model that any character can use, from day one onward
The game never ends and keeps adding opportunities, so the model must keep growing with it (new activities, agents, programs, skills are DATA, not code).
`next` must always pick the ONE best next step for where the character is, by modeling EVERY option each time:
cash ISK per minute + what the step teaches the model + progression/unlock value + route extras (trades both ways, agents on the route, cheap gear on the route),
looking several steps ahead when a chain of steps pays more in the long run. If there are no open questions it just says do it.
Layers (each is a file or two, all data-driven where possible):
1. DATA: `sync` (character), `scan` (markets), screenshots -> JSON files (offers, agents, sites, programs, catalog). Goal: fewer screenshots (more from ESI).
2. ACTIVITY CATALOG + MODELS: `activity_catalog.json`, timed runs (`start`/`stop`), `models`, `careers`: measured ISK/hr replaces guesses after 3 runs.
3. VALUE FUNCTION: `nextstep.py` candidates; `progress_values.json` (skills, standings, unlocks, model value); `bonus_programs.json` (rewards).
4. ROUTE EXTRAS: `tripplus.py` (agents on route, cheap needs, trades both ways), `makebuy.py` (make-or-buy), `dailygoals.py` (pair of goals), `haul.py`, `journey.py`.
5. PLANNER (next big step): rank ALL candidates WITH their route extras included, then look ahead 2-4 steps (e.g. train Astrometrics -> unlock scan goal + exploration career;
   buy a ship -> unlock a faster activity) and pick the first step of the best chain by ISK per minute over the whole chain.
6. SELF-IMPROVEMENT: model-building turns (try an unmodeled activity every 4th timer), each result lands in the DB and changes the ranking.
Open items for the planner: extras ISK inside the ranking (not only shown on the winner); skills/standings/unlock values per candidate; chain lookahead;
mining and reprocess-vs-buy for materials; ESI industry jobs scope; worldwide sale value for builds; per-character `profile` so a second character reuses the same model.
