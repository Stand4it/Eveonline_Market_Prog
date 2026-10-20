"""WHEN TO REFRESH PRICES BY HAND: the hourly task (scripts/hourly.bat) re-reads every market once an hour. So the prices we hold are never more than about an hour old and are
good for every item in the EVE world (every scanned region, not just this system). The rule (set by the user): under 30 minutes old, use them as they are. Past 30 minutes, the next scheduled run is nearer than a manual scan:
wait for it and run on the current prices. A manual `scan --live` is only worth recommending around the halfway point (30 minutes after the last run) and only when the decision
at hand really needs fresh prices (a big buy or sale)."""
import time

HALF = 30.0
WINDOW = 5.0            # a manual scan is only suggested within this many minutes of the halfway point


def age_min(con, region_id=None):
    """Minutes since the market orders were last downloaded: the STALEST scanned region (the whole world must be fresh), or `region_id`; None = never."""
    try:
        q, args = (("SELECT MAX(fetched_at) FROM orders WHERE region_id=?", (region_id,)) if region_id else
                   ("SELECT MIN(t) FROM (SELECT MAX(fetched_at) AS t FROM orders WHERE region_id>0 GROUP BY region_id)", ()))
        t = con.execute(q, args).fetchone()[0]
    except Exception:                                                   # noqa: BLE001
        return None
    return None if t is None else (time.time() - t) / 60.0


def advice(con, needed=False, now_age=None):
    """-> '' (say nothing: use the prices) or one line. Recommends a manual scan only at about 30 minutes past the last run AND only when a decision needs fresh prices."""
    age = age_min(con) if now_age is None else now_age
    if age is None:
        return "No prices yet: the hourly refresh fills them (or run  python -m eve_profit scan --live  once)."
    if abs(age - HALF) <= WINDOW and needed:
        return f"Prices are {age:.0f} min old, halfway between the hourly scans, and this decision needs them fresh: run  python -m eve_profit scan --live  first."
    return ""


def status_line(con):
    age = age_min(con)
    if age is None:
        return ""
    return f"(prices {age:.0f} min old" + ("" if age < HALF else f"; the next hourly refresh is in about {max(0, 60 - age):.0f} min: going on the current prices") + ")"
