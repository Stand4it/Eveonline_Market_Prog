# EVE Profit Planner - status (saved 2026-10-05)

Repo: `stand4it/eveonline_market_prog`, branch `claude/dreamy-edison-n9n32f`. 83 unit tests pass.
Runs on the user's Windows PC (`C:\Users\Martin Dahl\Documents\eveonline_market_prog`), database `E:\EveProfit\eve_profit.db`.
Character: Stand Dahldaberg (Mammoth, Hek). Other characters: Dahldaberg02, Dahldaberg3 (not yet supported).

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
