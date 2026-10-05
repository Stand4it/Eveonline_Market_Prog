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
