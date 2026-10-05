# EVE Profit Planner

Ranks what to do *right now* (haul trades, sell stock, mine) by risk-adjusted **ISK/hour** and **ISK/jump**.

    scripts\setup.bat      # Windows: creates E:\EveProfit\eve_profit.db, runs tests + demo
    scripts\watch_mock.bat # offline simulated market, rescans continuously
    scripts\go_live.bat    # live ESI market data (no login)

Linux/Mac: `scripts/run.sh mock|scan|live`. Edit `profile.json` for ship, cargo m3, system, mining yield.
DB path override: env `EVE_PROFIT_DB`. Safety: sec<0.5 never routed; 0.5-0.6 & recently-kill-hot systems penalised.
See ROADMAP.md.

## EVE login (Stage 3)
1. https://developers.eveonline.com -> Create application, type *Authentication & API Access*.
2. Callback URL `http://localhost:8801/callback`; scopes: location, ship type, skills, wallet, assets, ui waypoint.
3. `set EVE_CLIENT_ID=<client id>` then `scripts\login.bat` (login -> sync profile/inventory -> live scan).
No client secret is used (PKCE). Tokens are saved to `tokens.json` (git-ignored; keep private).
`sync` sets: system, ship name, cargo m3, wallet, Accounting level. Mining yield and ship value stay manual.

## Manufacturing (Stage 4)
Uses your blueprints (`sync` loads them; re-run `login` once to grant the new blueprint scope) or set
`"assume_all_blueprints": true` in profile.json to rank everything buildable. Materials come from the
cheapest in-range ask, product sells into buy orders. Ranking uses *your active time*; the build job runs in
the background (`job_hours` is shown). Skill requirements and slot limits are not checked yet.

## Combat & salvage (Stage 5)
Set `combat_dps` (your real DPS), `can_salvage` in profile.json. Activities live in the `activities` table
(seeded placeholders, edit freely). Log real results so estimates become your own averages after 3 runs:

    python -m eve_profit log --activity "Level 3 security mission" --isk 28000000 --hours 1.1

Rules baked in: NPC targets and your own wrecks only (no ganking / no taking others' wrecks); red never routed;
systems with recent kills skipped; expected ship loss and docking-wait time are charged against ISK/hr.

## Route automation (Stage 6)
    python -m eve_profit go --pick 2          # dry run: shows waypoints for ranked opportunity #2
    python -m eve_profit go --pick 2 --send   # sets them in your running game client (needs login)
`scripts\go.bat [N]` does the send. It places a waypoint at every system on the safe path (so the in-game
router can't detour through red), refuses any route with a red system, and prints ALERT lines for
hot/recent-kill systems; `watch` also beeps when the best route turns hot. ESI only sets waypoints:
you still engage autopilot or fly manually (set `"autopilot": true` in profile.json for slower timing).
Re-run `login` once if you logged in before Stage 3 so the waypoint scope is granted.

### Combat win-odds (safety gate)
Combat is only recommended if the planner can show you win. Set in profile.json: `combat_dps`, `ship_ehp`
(fit's effective HP), `ship_tank_dps` (sustained repair), `ship_value_isk`/`fit_value_isk`, `ship_type_id`
(sync sets it), optional `insurance_payout_isk`. Per wave: damage taken = (enemy threat dps - your tank) x
(enemy ehp / your dps); margin = ship_ehp / damage. Offered only if margin >= `min_win_margin` (3.0), or
margin >= `risky_win_margin` (1.5) AND one session's profit >= the ship's replacement cost (cheaper of buying
the hull in range or building it from a blueprint you own, plus fit, minus insurance). The expected loss
(lose-chance x replacement cost) is subtracted from ISK/hr and the win % is shown. With `ship_ehp` = 0 no combat
is shown. Enemy ehp/threat numbers are placeholders in the `activities` table: log real results (log a lost
ship as a negative ISK run) and calibrate.

## Contracts & player offers
Market player orders were already scanned (buy/sell orders are player offers). `--live` scans now also pull
public contracts for the region(s) (no login): **item-exchange/auction** bundles whose contents sell for more
than their price (contents valued at best buy orders in range; blueprint copies and unpriced items count as 0)
and **courier** jobs ranked by reward per jump/hour (cargo, collateral and wallet checked). Contracts in player
structures are skipped (system unknown without login). "CHECK-IN-GAME" marks margins >3x: look-alike-item scams
exist, so open the contract and verify every item before accepting. Contents are fetched 150 contracts per scan.

## Skill & slot checks
`sync` stores your trained skills, manufacturing slots (1 + Mass Production + Advanced Mass Production) and
running jobs. Builds are skipped if you lack a blueprint skill (shown as "blocked build: X - needs Industry 3
(have 2)" after a scan), BPC runs cap the batch, and at most one build per free slot is ranked. Ores needing a
skill you lack are skipped for mining. Before your first sync (no skills stored) the skill check is skipped.
Re-run `login` once to grant the new industry-jobs scope. Not checked: ship/module fitting skills for combat.

## Mission agents & LP stores
- **LP value:** each corporation's LP store offers (public ESI, cached 24h) are priced as
  (reward sold into buy orders - ISK cost - required items bought at cheapest asks) / LP cost = **ISK per LP**.
- **Missions:** level 2/3/4 mission activities now need a real agent of that level in range (from the SDE),
  usable with your standing (best of agent/corp/faction standing, no Connections/Diplomacy bonus - approximate),
  and add `lp_per_hour x ISK/LP` of that agent's corporation to the mission's ISK/hr. LP-per-hour and
  minimum-standing numbers are placeholders in the `activities` table; log real runs to calibrate.
- **Redeem:** `lp-redeem` opportunities turn LP you already hold into ISK (best offer per corporation with a
  store in range; never more than your LP, wallet or cargo). Missions *earn* LP and redeeming *spends* it, so
  don't add the two together.
- Needs login: LP balance and standings (re-run `login` for the two new scopes). Without sync, standings are
  assumed OK and no redeem offers appear. LP stores in stations outside the SDE (player structures) are not seen.

## Structure markets (player citadels)
With `--live` and a saved login, each scan lists public market structures, reads which ones you can dock at
(no access = remembered for a week, not retried), and downloads orders for accessible ones in range (20 per
scan; add your own with `"structure_ids": [..]` in profile.json). Their orders join the normal books, so
trades, contracts, builds and LP redeems can use them, and contracts located in known structures now resolve.
`structure_sales_tax` (default 1%, owners set their own - check in game) is shaved off structure buy orders.
Needs two more scopes (re-run `login`): structure markets + read structures. Caveats: you must be able to
dock there (hostile/blue-list rules change), and structures in low/null space are avoided by the router.

## Universe data (replaces the Fuzzwork download)
`python -m eve_profit universe` loads the map once, trying in order:
1. CCP's official SDE (JSONL zip, `developers.eveonline.com/static-data/...`) - systems, gates, stations, types,
   blueprints, skills, agents. Or import a zip you downloaded: `universe --sde-file "C:\path\sde.zip"`.
2. If that fails, it builds the map **around your system from ESI** (`--depth N` jumps, default 3x your radius).
   No blueprint or agent data in this mode (ESI has no endpoint for them), so builds and mission agents are
   skipped until the SDE import works. Stations are learned from ESI as they turn up.
`login.bat` runs: login -> sync (learns your system) -> universe -> sync again -> live scan.

## Playing nicely with other bots
- Only one `watch`, one `login` and one setup command (`sync`/`universe`/`sde`/`mock`) can run per database; a second
  one stops with "already running (PID n)". Locks are `<db>.<kind>.lock` files; a lock left by a killed window is
  detected and replaced automatically. `scan`/`plan`/`go` are not locked (SQLite handles concurrent reads).
- The login callback port is 8801 (override with `EVE_CALLBACK_PORT`, and change the app's callback URL to match);
  it is open only while logging in. No background services, startup items or files outside the repo and `E:\EveProfit`.
