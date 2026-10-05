# Stock Screens — email recommendation paper-trader

Tracks the stock recommendations you get by email as if you had bought each one,
and answers two questions for every pick:

1. **Is it beating SPY?** Total return (price + dividends) from the recommendation
   date vs. SPY over the exact same dates — and is it *still* beating it
   (last ~month, plus a win streak across daily runs)?
2. **Does it pay more than the bank?** Forward dividend yield (today and on your
   paper entry price) vs. the **4.09%** bank rate, counted only when the
   dividend has been stable or growing (not cut).

Each pick also gets the return the same money would have earned in the bank at 4.09%.

## Files

| File | What it is |
|---|---|
| `recommendations.csv` | Your picks: `rec_date,ticker,source,notes` (date = `YYYY-MM-DD`) |
| `config.json` | Benchmark, bank rate, position size, email search |
| `tracker.py` | Prices everything and writes `report.md` + appends `history.csv` |
| `email_ingest.py` | Reads newsletter emails over IMAP and adds tickers to the CSV |
| `report.md` | The scoreboard (regenerated each run) |
| `history.csv` | One snapshot per pick per run, so you can see if a pick keeps beating SPY |

## Quick start (on your computer)

```bash
cd stock_screens
pip install -r requirements.txt
# add picks by hand...
echo "2026-09-15,KO,Motley Fool,dividend pick" >> recommendations.csv
python tracker.py          # -> report.md
```

## Pull picks from email

1. In Gmail: turn on IMAP and create an **App Password** (Google Account →
   Security → 2-Step Verification → App passwords).
2. Edit `config.json` → `email.search` to match the newsletters, e.g.
   `(FROM "alerts@fool.com")` or `(SUBJECT "Stock Pick")`.
3. Run:
   ```bash
   export STOCK_EMAIL_USER=you@gmail.com
   export STOCK_EMAIL_PASSWORD=your-app-password
   python email_ingest.py --dry-run   # preview
   python email_ingest.py
   ```
It recognises `$TICKER`, `(NYSE: TICKER)` and `(NASDAQ: TICKER)`. Check the CSV
afterwards and delete tickers that were only mentioned, not recommended.

## Run it automatically (GitHub Actions)

`.github/workflows/stock-tracker.yml` runs every weekday after the close,
imports new emails (if the `STOCK_EMAIL_USER` / `STOCK_EMAIL_PASSWORD` repo
secrets are set), refreshes `report.md`, and commits the results. Start it
manually from the **Actions** tab with *Run workflow*.

## Verdicts

- 🏆 **Beats SPY + income** — ahead of SPY and pays a consistent yield ≥ 4.09%
- ✅ **Beats SPY** — ahead since the recommendation (*fading* = behind SPY over the last month)
- 💵 **Income > bank** — behind SPY but yields more than the bank, with a steady dividend
- ❌ **Lagging** — neither

Market data comes from Yahoo Finance (via `yfinance`). Paper trading only: no taxes,
commissions, or advice.
