"""Paper-trade stock recommendations and compare them against SPY and a bank rate.

Every recommendation in recommendations.csv is treated as a hypothetical buy of
`position_size_usd` at the close on (or after) its recommendation date, held to
today. Each pick is measured three ways:

  * total return (price + dividends) vs. SPY total return over the same window
  * forward dividend yield (today and on your entry price) vs. the bank rate
  * whether it is *still* beating SPY recently, and how many tracker runs in a
    row it has been ahead (history.csv keeps one snapshot per run)

Usage:
    python tracker.py                 # update report.md and history.csv
    python tracker.py --no-history    # report only, don't append a snapshot
"""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent


# --------------------------------------------------------------------------- data


class YahooData:
    """Market data from Yahoo Finance via yfinance."""

    def __init__(self):
        import yfinance as yf

        self._yf = yf
        self._cache: dict[str, pd.DataFrame] = {}

    def prices(self, ticker: str, start: date) -> pd.DataFrame:
        """Daily `close` (raw) and `adj_close` (dividend/split adjusted) from start."""
        key = f"{ticker}:{start}"
        if key not in self._cache:
            df = self._yf.download(
                ticker, start=start.isoformat(), auto_adjust=False, progress=False
            )
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.rename(columns={"Close": "close", "Adj Close": "adj_close"})
            df.index = pd.to_datetime(df.index).tz_localize(None)
            self._cache[key] = df[["close", "adj_close"]].dropna()
        return self._cache[key]

    def dividends(self, ticker: str) -> pd.Series:
        s = self._yf.Ticker(ticker).dividends
        if len(s):
            s.index = pd.to_datetime(s.index).tz_localize(None)
        return s

    def forward_dividend_rate(self, ticker: str) -> float | None:
        """Annual forward dividend per share, if Yahoo publishes one."""
        try:
            rate = self._yf.Ticker(ticker).info.get("dividendRate")
        except Exception:
            return None
        return float(rate) if rate else None


# ------------------------------------------------------------------------ models


@dataclass
class Rec:
    rec_date: date
    ticker: str
    source: str = ""
    notes: str = ""


@dataclass
class Result:
    rec: Rec
    entry_date: date | None = None
    entry_price: float | None = None
    last_price: float | None = None
    days_held: int = 0
    total_return: float | None = None
    spy_return: float | None = None
    bank_return: float | None = None
    recent_excess: float | None = None
    fwd_yield: float | None = None
    yield_on_cost: float | None = None
    dividend_trend: str = "n/a"
    streak: int = 0
    error: str = ""

    @property
    def excess(self) -> float | None:
        if self.total_return is None or self.spy_return is None:
            return None
        return self.total_return - self.spy_return

    def beats_spy(self) -> bool:
        return self.excess is not None and self.excess > 0

    def income_pick(self, bank_rate: float) -> bool:
        y = self.fwd_yield
        return (
            y is not None
            and y >= bank_rate
            and self.dividend_trend in ("growing", "stable")
        )

    def verdict(self, bank_rate: float) -> str:
        if self.error:
            return "⚠️ no data"
        beats, income = self.beats_spy(), self.income_pick(bank_rate)
        if beats and income:
            return "🏆 Beats SPY + income"
        if beats:
            still = self.recent_excess is not None and self.recent_excess > 0
            return "✅ Beats SPY" + ("" if still else " (fading)")
        if income:
            return "💵 Income > bank"
        return "❌ Lagging"


@dataclass
class Config:
    benchmark: str = "SPY"
    bank_rate_pct: float = 4.09
    position_size_usd: float = 1000.0
    recent_window_trading_days: int = 21
    email: dict = field(default_factory=dict)

    @property
    def bank_rate(self) -> float:
        return self.bank_rate_pct / 100

    @classmethod
    def load(cls, path: Path) -> "Config":
        if not path.exists():
            return cls()
        return cls(**json.loads(path.read_text()))


# ----------------------------------------------------------------------- loading


def load_recs(path: Path) -> list[Rec]:
    recs = []
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            ticker = (row.get("ticker") or "").strip().upper()
            when = (row.get("rec_date") or "").strip()
            if not ticker or not when or when.startswith("#"):
                continue
            recs.append(
                Rec(
                    rec_date=datetime.strptime(when, "%Y-%m-%d").date(),
                    ticker=ticker,
                    source=(row.get("source") or "").strip(),
                    notes=(row.get("notes") or "").strip(),
                )
            )
    return recs


# ------------------------------------------------------------------- calculation


def window_return(px: pd.DataFrame, start: pd.Timestamp, col: str = "adj_close"):
    """Return from the first bar on/after `start` to the last bar."""
    sub = px[px.index >= start]
    if sub.empty:
        return None, None
    return float(sub[col].iloc[-1] / sub[col].iloc[0] - 1), sub.index[0]


def dividend_trend(divs: pd.Series, today: date) -> str:
    """Classify the last 3 trailing years of dividends: growing/stable/cut/none."""
    if divs is None or divs.empty:
        return "none"
    end = pd.Timestamp(today)
    years = []
    for i in range(3):
        hi, lo = end - pd.DateOffset(years=i), end - pd.DateOffset(years=i + 1)
        years.append(float(divs[(divs.index > lo) & (divs.index <= hi)].sum()))
    ttm, prev, prev2 = years
    if ttm == 0:
        return "none"
    if prev == 0:
        return "new"
    if ttm < prev * 0.95:
        return "cut"
    if ttm > prev * 1.02 and (prev2 == 0 or prev >= prev2 * 0.98):
        return "growing"
    return "stable"


def evaluate(rec: Rec, data, cfg: Config, today: date) -> Result:
    r = Result(rec=rec)
    start = pd.Timestamp(rec.rec_date)
    try:
        px = data.prices(rec.ticker, rec.rec_date)
        spy = data.prices(cfg.benchmark, rec.rec_date)
    except Exception as e:  # network / unknown ticker
        r.error = str(e)
        return r
    if px is None or px.empty or spy is None or spy.empty:
        r.error = "no price data"
        return r

    r.total_return, entry_ts = window_return(px, start)
    r.spy_return, _ = window_return(spy, entry_ts)
    if r.total_return is None:
        r.error = "no price data since rec date"
        return r

    r.entry_date = entry_ts.date()
    r.entry_price = float(px.loc[entry_ts, "close"])
    r.last_price = float(px["close"].iloc[-1])
    r.days_held = (today - r.entry_date).days
    r.bank_return = (1 + cfg.bank_rate) ** (r.days_held / 365) - 1

    n = cfg.recent_window_trading_days
    if len(px) > n and len(spy) > n:
        recent_start = px.index[-n - 1]
        pr, _ = window_return(px, recent_start)
        sr, _ = window_return(spy, recent_start)
        if pr is not None and sr is not None:
            r.recent_excess = pr - sr

    divs = data.dividends(rec.ticker)
    r.dividend_trend = dividend_trend(divs, today)
    rate = data.forward_dividend_rate(rec.ticker)
    if rate is None and divs is not None and not divs.empty:
        cutoff = pd.Timestamp(today) - pd.DateOffset(years=1)
        rate = float(divs[divs.index > cutoff].sum()) or None
    if rate:
        r.fwd_yield = rate / r.last_price
        r.yield_on_cost = rate / r.entry_price
    return r


# ----------------------------------------------------------------------- history


HISTORY_FIELDS = ["run_date", "ticker", "rec_date", "total_return", "spy_return",
                  "excess", "fwd_yield"]


def append_history(path: Path, results: list[Result], today: date) -> None:
    new = not path.exists()
    existing = set()
    if not new:
        with path.open(newline="") as f:
            existing = {(row["run_date"], row["ticker"], row["rec_date"])
                        for row in csv.DictReader(f)}
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_FIELDS)
        if new:
            w.writeheader()
        for r in results:
            if r.error:
                continue
            key = (today.isoformat(), r.rec.ticker, r.rec.rec_date.isoformat())
            if key in existing:
                continue
            w.writerow({
                "run_date": key[0], "ticker": key[1], "rec_date": key[2],
                "total_return": f"{r.total_return:.6f}",
                "spy_return": f"{r.spy_return:.6f}",
                "excess": f"{r.excess:.6f}",
                "fwd_yield": "" if r.fwd_yield is None else f"{r.fwd_yield:.6f}",
            })


def apply_streaks(path: Path, results: list[Result]) -> None:
    """Consecutive tracker runs (most recent first) in which each pick beat SPY."""
    if not path.exists():
        return
    hist = pd.read_csv(path)
    for r in results:
        rows = hist[(hist.ticker == r.rec.ticker)
                    & (hist.rec_date == r.rec.rec_date.isoformat())]
        streak = 0
        for excess in rows.sort_values("run_date", ascending=False).excess:
            if excess <= 0:
                break
            streak += 1
        r.streak = streak


# ------------------------------------------------------------------------ report


def pct(x: float | None, signed: bool = True) -> str:
    if x is None:
        return "—"
    return f"{x * 100:+.2f}%" if signed else f"{x * 100:.2f}%"


def portfolio_summary(results: list[Result], cfg: Config) -> dict:
    ok = [r for r in results if not r.error]
    size = cfg.position_size_usd
    invested = size * len(ok)
    return {
        "picks": len(ok),
        "invested": invested,
        "picks_value": sum(size * (1 + r.total_return) for r in ok),
        "spy_value": sum(size * (1 + r.spy_return) for r in ok),
        "bank_value": sum(size * (1 + r.bank_return) for r in ok),
        "beat_spy": sum(r.beats_spy() for r in ok),
        "income": sum(r.income_pick(cfg.bank_rate) for r in ok),
    }


def render_report(results: list[Result], cfg: Config, today: date) -> str:
    s = portfolio_summary(results, cfg)
    bank = f"{cfg.bank_rate_pct:.2f}%"
    lines = [
        f"# Stock recommendation paper-trading report — {today.isoformat()}",
        "",
        f"Each pick = hypothetical ${cfg.position_size_usd:,.0f} bought at the close on its "
        f"recommendation date. Returns include dividends. Benchmarks: **{cfg.benchmark}** "
        f"(same dates, same dollars) and a **{bank} bank account**.",
        "",
        "## Scoreboard",
        "",
    ]
    if s["picks"]:
        def line(name, v):
            return f"| {name} | ${v:,.2f} | {pct(v / s['invested'] - 1)} |"
        lines += [
            "| Strategy | Value now | Return |",
            "|---|---:|---:|",
            line("Following the recommendations", s["picks_value"]),
            line(f"Same money in {cfg.benchmark}", s["spy_value"]),
            line(f"Same money in bank @ {bank}", s["bank_value"]),
            "",
            f"- Picks beating {cfg.benchmark}: **{s['beat_spy']} / {s['picks']}**",
            f"- Picks with consistent forward yield ≥ {bank}: **{s['income']} / {s['picks']}**",
            "",
        ]
    else:
        lines += ["_No recommendations with price data yet. Add rows to "
                  "`recommendations.csv` or run `email_ingest.py`._", ""]

    lines += [
        "## Picks",
        "",
        f"| Verdict | Ticker | Rec date | Source | Entry | Last | Days | Return | "
        f"{cfg.benchmark} | vs {cfg.benchmark} | Last {cfg.recent_window_trading_days}d vs "
        f"{cfg.benchmark} | Win streak | Fwd yield | Yield on cost | Dividend trend |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    order = sorted(results, key=lambda r: (r.error != "", -(r.excess or -9)))
    for r in order:
        money = (lambda v: "—" if v is None else f"${v:,.2f}")
        lines.append(
            f"| {r.verdict(cfg.bank_rate)} | **{r.rec.ticker}** | {r.rec.rec_date} | "
            f"{r.rec.source or '—'} | {money(r.entry_price)} | {money(r.last_price)} | "
            f"{r.days_held} | {pct(r.total_return)} | {pct(r.spy_return)} | "
            f"{pct(r.excess)} | {pct(r.recent_excess)} | {r.streak} | "
            f"{pct(r.fwd_yield, False)} | {pct(r.yield_on_cost, False)} | {r.dividend_trend} |"
        )
    errors = [r for r in results if r.error]
    if errors:
        lines += ["", "### Data problems", ""]
        lines += [f"- {r.rec.ticker} ({r.rec.rec_date}): {r.error}" for r in errors]
    lines += [
        "",
        "## How to read this",
        "",
        f"- **🏆 Beats SPY + income** — ahead of {cfg.benchmark} *and* forward yield ≥ {bank} "
        "with a stable or growing dividend.",
        f"- **✅ Beats SPY** — ahead of {cfg.benchmark} since the recommendation. "
        f"*(fading)* = it has lagged {cfg.benchmark} over the last "
        f"{cfg.recent_window_trading_days} trading days.",
        f"- **💵 Income > bank** — behind {cfg.benchmark}, but pays a consistent forward "
        f"yield above your {bank} bank rate.",
        "- **Win streak** — consecutive tracker runs the pick has been ahead of "
        f"{cfg.benchmark}; this is how you see whether it *keeps* beating it going forward.",
        "- **Yield on cost** — forward annual dividend ÷ your paper entry price.",
        "- **Dividend trend** — trailing-12-month dividends vs the prior year "
        "(cut = down more than 5%).",
        "",
        "_Paper trading only; ignores taxes and commissions. Not financial advice._",
    ]
    return "\n".join(lines) + "\n"


# -------------------------------------------------------------------------- main


def run(recs_path: Path, cfg: Config, data, today: date, history_path: Path | None):
    results = [evaluate(r, data, cfg, today) for r in load_recs(recs_path)]
    if history_path is not None:
        append_history(history_path, results, today)
        apply_streaks(history_path, results)
    return results


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--recs", type=Path, default=HERE / "recommendations.csv")
    p.add_argument("--config", type=Path, default=HERE / "config.json")
    p.add_argument("--history", type=Path, default=HERE / "history.csv")
    p.add_argument("--report", type=Path, default=HERE / "report.md")
    p.add_argument("--no-history", action="store_true")
    args = p.parse_args(argv)

    cfg = Config.load(args.config)
    today = date.today()
    results = run(args.recs, cfg, YahooData(), today,
                  None if args.no_history else args.history)
    args.report.write_text(render_report(results, cfg, today))
    s = portfolio_summary(results, cfg)
    print(f"{s['picks']} picks | beating {cfg.benchmark}: {s['beat_spy']} | "
          f"income ≥ {cfg.bank_rate_pct}%: {s['income']} -> {args.report}")


if __name__ == "__main__":
    main()
