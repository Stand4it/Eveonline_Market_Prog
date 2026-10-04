# EVE Profit Planner

Ranks what to do *right now* (haul trades, sell stock, mine) by risk-adjusted **ISK/hour** and **ISK/jump**.

    scripts\setup.bat      # Windows: creates E:\EveProfit\eve_profit.db, runs tests + demo
    scripts\watch_mock.bat # offline simulated market, rescans continuously
    scripts\go_live.bat    # live ESI market data (no login)

Linux/Mac: `scripts/run.sh mock|scan|live`. Edit `profile.json` for ship, cargo m3, system, mining yield.
DB path override: env `EVE_PROFIT_DB`. Safety: sec<0.5 never routed; 0.5-0.6 & recently-kill-hot systems penalised.
See ROADMAP.md.
