# EVE Profit Planner - status (updated 2026-10-07). READ md/START_HERE.md FIRST.

Repo: `stand4it/eveonline_market_prog`, branch `claude/dreamy-edison-n9n32f`. tests (count: see STATE.md) pass.
Runs on the user's Windows PC (`C:\Users\Martin Dahl\OneDrive\Documents\EVE\eveonline`), database `E:\EveProfit\eve_profit.db`.
Characters: Stand Dahldaberg (main), Dahldaberg02, Dahldaberg3, Stand4it Dahl (new experiment). Multi-character is supported (see md/START_HERE.md).

## Verified on real data (user's PC)
- Python 3.13, tests, E: database, mock demo (separate `E:\EveProfit\mock.db`).
- EVE SSO login (Client ID in `client_id.txt`/env, callback `http://localhost:8801/callback`), `sync`.
- Official SDE (JSONL zip) import: 8,490 systems, 13,978 gates, 5,210 stations, 27,133 types, 4,849 blueprints, 8,775 agents.
- Live scan: ~330k orders, 2,325 contracts, 40 LP stores, 3 structure markets (4,908 orders); ranking takes ~2 s.
- First real ranking: top trade = Datacore - Minmatar Starship Engineering, buy @ Hek, sell @ Pator (~464k ISK, ~5.5M ISK/hr).

## Built (all stages)
trade/haul, liquidation of own stock (includes trip + cargo cap), mining, manufacturing (ME/TE, fees, slots, skills),
contracts (bundles + courier), LP stores + redemption, mission agents (standings), combat with win-odds gate and
ship-replacement cost, salvage, structure markets, fleet/ship-swap planning, away mode (long safe autopilot hauls,
auto-dock waypoints), route automation (`go`), skill advisor, single-instance locks, universe loader (SDE + ESI fallback).

## Commands
`scan` (re-rank stored data, seconds) | `scan --live` (download, 10-15 min apart) | `watch --live` | `go --pick N [--send] [--away]`
| `fleet` | `skills --hours 72` | `diag` | `sync` | `login` | `universe` | `log --activity X --isk N --hours H`
Env: `EVE_CLIENT_ID`, `EVE_CALLBACK_PORT` (8801), `EVE_PROFIT_DB`, `EVE_PROFIT_TIMING=1`.

## Open items / next steps
1. User to run: `git pull; sync; diag; skills --hours 72` and paste output (advisor needs ESI-fetched skill ranks; Mammoth cargo
   bonus should now use "Minmatar Hauler" IV; parked-ship hold sizes now filled from ESI).
2. User to report real prices for the Hek -> Pator datacore trade to calibrate accuracy.
3. Fill `profile.json`: ship_ehp, ship_tank_dps, ship_value_isk (placeholder 20M), mining yield, combat dps, per-hull `ships` stats.
4. Not built: multi-character support (helper characters), journey composer (fill spare cargo / backhauls along the route),
   blueprint purchase payback, full chain planner (buy mats > build > haul > sell), consolidating duplicate trades
   (same item to several buyers), per-structure tax, contract-location station ids for auto-dock.
5. Known limits: all payout/threat numbers for combat/missions are placeholders; align/speed skill effects are estimates;
   cargo bonus assumes +5%/level for racial hauler/industrial skills; EVE client on user PC had memory trouble (64 GB RAM arriving).
6. Security: a Client Secret was shown in a screenshot earlier - rotate it in the developer portal (this program doesn't use it).


## Principle (from the user)
Keep EVERY way of making ISK on the table and keep progressing: re-rank as skills, ships, blueprints, stock, wallet and
game patches change. Profit is the key; stay safe (red never routed, loss-aware, no suicide ganking).

## Added since the first live run
`explain` / `check` (live item check before buying) | `stock` (value of what you own, best hold-loads) | `along` (sell on the way,
SELL NOW vs LIST, order slots, route watch, cost basis) | `fit` (what is fitted) | `zkill` (hauler-loss map) | `next` (one step
at a time) | `keep` (build vs sell owned materials) | `bpbuy` (buy a blueprint to use stock) | `update` (new game data after a patch).

## Backlog, in priority order (agreed)
1. Ship shopping advisor: which hull to BUY or BUILD (and fit/pilot, skills allowing) raises ISK/hr most, with payback time
   (cargo hulls are measurable now; combat hulls need Pyfa numbers in profile.json `ships`).
2. Journey composer: main task + minor trades/backhauls along the route with spare hold space.
3. Character contracts (needs scope esi-contracts.read_character_contracts.v1): your open/expiring couriers; accepted jobs.
4. Agents/missions: real offers are NOT in ESI; calibrate with `log` after each mission (isk/LP/time/losses) so estimates
   become your own averages; standings-gated agent finder already exists.
5. "Kill contracts"/bounties: no public API; zKillboard only shows killmails. Revisit if CCP adds an endpoint.
6. Patch watch: run `update` after each patch (new items/blueprints/ships/skills), then `universe --force`, `scan --live`,
   `bpbuy`, `skills`.
7. Multi-character (Dahldaberg02, Dahldaberg3) as helper pilots; corp assets/blueprints if the corp is active.
8. Reactions, invention/T2, PI, exploration/abyssal loot valuation, market-making (order-based station trading).

## Where we are (latest)
Built: `now` (one-command next step), `journey` / `compare` (trip and list-vs-trip by ISK per active minute), automatic character pick (online one), `trainplan` (what to train now/next), `start`/`stop`/`activities` (measured ISK/hr from the wallet journal, with loot valued net of travel time), `combatfit`, caching (skip fresh regions, save per region).
Not yet verified on live data: `journey`, `compare`, loot valuation in `stop`, `stop` payouts from the real wallet journal.
Next ideas: career-agent activities in the planner; scale measured level-1 results to higher levels by ship and skill points; training suggestions that improve the model; patient buy orders for away time; auto-snapshot of the hangar for loot; reprocess-or-sell check; ship shopping advisor.
Lesson: after any edit to `cli.py`, run the tests: `tests/test_cli_dispatch.py` catches a command that lost its branch.
