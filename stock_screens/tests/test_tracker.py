import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tracker  # noqa: E402
from email_ingest import extract_tickers  # noqa: E402

TODAY = date(2026, 10, 2)


class FakeData:
    """Linear price paths: each ticker grows by a fixed % per trading day."""

    def __init__(self, daily, divs=None, fwd=None):
        self.daily, self.divs, self.fwd = daily, divs or {}, fwd or {}

    def prices(self, ticker, start):
        idx = pd.bdate_range("2026-01-02", TODAY)
        g = (1 + self.daily[ticker]) ** pd.Series(range(len(idx)), index=idx)
        df = pd.DataFrame({"close": 100 * g, "adj_close": 100 * g})
        return df[df.index >= pd.Timestamp(start)]

    def dividends(self, ticker):
        return self.divs.get(ticker, pd.Series(dtype=float))

    def forward_dividend_rate(self, ticker):
        return self.fwd.get(ticker)


def quarterly(amounts):
    """Quarterly dividends ending just before TODAY, oldest first."""
    idx = pd.date_range(end="2026-09-15", periods=len(amounts), freq="3MS")
    return pd.Series(amounts, index=idx)


@pytest.fixture
def recs(tmp_path):
    p = tmp_path / "recs.csv"
    p.write_text(
        "rec_date,ticker,source,notes\n"
        "2026-03-02,WIN,news@x.com,\n"
        "2026-03-02,INC,news@x.com,\n"
        "2026-03-02,LAG,news@x.com,\n"
    )
    return p


def make_data():
    return FakeData(
        {"SPY": 0.0005, "WIN": 0.001, "INC": 0.0002, "LAG": 0.0001},
        divs={"INC": quarterly([0.5] * 4 + [0.52] * 4 + [0.55] * 4)},
        fwd={"INC": 2.2 * 2.0},  # forward rate chosen so yield is high
    )


def test_verdicts_and_returns(recs, tmp_path):
    cfg = tracker.Config()
    res = {r.rec.ticker: r for r in
           tracker.run(recs, cfg, make_data(), TODAY, tmp_path / "h.csv")}

    assert res["WIN"].beats_spy() and res["WIN"].verdict(cfg.bank_rate) == "✅ Beats SPY"
    assert not res["INC"].beats_spy()
    assert res["INC"].dividend_trend == "growing"
    assert res["INC"].fwd_yield > cfg.bank_rate
    assert res["INC"].verdict(cfg.bank_rate) == "💵 Income > bank"
    assert res["LAG"].verdict(cfg.bank_rate) == "❌ Lagging"
    # bank return over ~7 months at 4.09%
    assert res["WIN"].bank_return == pytest.approx(
        1.0409 ** (res["WIN"].days_held / 365) - 1)


def test_streak_counts_consecutive_runs(recs, tmp_path):
    cfg, hist, data = tracker.Config(), tmp_path / "h.csv", make_data()
    for d in (date(2026, 9, 30), date(2026, 10, 1), TODAY):
        res = tracker.run(recs, cfg, data, d, hist)
    res = {r.rec.ticker: r for r in res}
    assert res["WIN"].streak == 3
    assert res["LAG"].streak == 0
    # rerunning on the same day must not duplicate snapshot rows
    tracker.run(recs, cfg, data, TODAY, hist)
    assert len(pd.read_csv(hist)) == 9


def test_dividend_trend():
    assert tracker.dividend_trend(pd.Series(dtype=float), TODAY) == "none"
    assert tracker.dividend_trend(quarterly([1] * 8 + [0.5] * 4), TODAY) == "cut"
    assert tracker.dividend_trend(quarterly([1] * 12), TODAY) == "stable"


def test_report_renders(recs, tmp_path):
    cfg = tracker.Config()
    res = tracker.run(recs, cfg, make_data(), TODAY, None)
    out = tracker.render_report(res, cfg, TODAY)
    assert "Following the recommendations" in out
    assert "**WIN**" in out and "4.09%" in out


def test_extract_tickers():
    text = "Buy $KO and Altria (NYSE: MO) now; also $BRK.B. Priced in $USD. (NASDAQ: MSFT)"
    assert extract_tickers(text) == ["KO", "BRK-B", "MO", "MSFT"]
