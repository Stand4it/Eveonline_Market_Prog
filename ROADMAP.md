# Roadmap (stages)

| Stage | Scope | Needs EVE login? | Status |
|---|---|---|---|
| 1 | SQLite DB (E:\EveProfit), universe graph, red-avoid/yellow-penalty routing, hauling-trade + inventory-liquidation + mining ranking by ISK/hr & ISK/jump, mock data, tests | No | **Done** |
| 2 | Live public data: SDE universe import, ESI regional orders, kill-feed risk, continuous `watch` scanning, long-haul ranges | No (public ESI; run on your PC) | Code written, **unverified** (sandbox blocks ESI) |
| 3 | EVE SSO (PKCE) login: location, ship + cargo, skills (tax/mining yield), wallet, assets -> auto-fill profile; structure markets | **Yes** - you register an app at developers.eveonline.com | Next |
| 4 | Manufacturing/reactions (blueprints, skills, material cost vs sell, build time), player-contract/offer scanning | Yes (skills/BPOs) | |
| 5 | Salvage + NPC combat/missions as ISK/hr candidates, safe-only rules | Yes | |
| 6 | Automation: route-setting via ESI waypoint API (`ui/autopilot/waypoint`), manual-vs-autopilot timing, "dock when hot" alerts | Yes | |

Ground rules: no suicide-ganking/ninja-looting by default; red systems never routed; yellow penalised.
CCP rules: ESI cannot move your ship; it can only set waypoints. Automating in-game input is not allowed.
