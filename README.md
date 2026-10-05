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
2. Callback URL `http://localhost:8765/callback`; scopes: location, ship type, skills, wallet, assets, ui waypoint.
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
