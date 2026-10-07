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
