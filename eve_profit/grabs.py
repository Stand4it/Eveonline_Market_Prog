"""Everything the tool can read from the game by program, on its own schedule. `now` runs every grab that is DUE (so market prices and these stay fresh
together); a one-off need is a step in `next` instead. Add a grab: one entry in GRABS (id, label, hours between runs, function(con) -> one-line result)."""
import time


def _freelance(con):
    """-> (summary, share of the list that changed, ESI cache end as an HTTP date or None)."""
    from .freelance import LAST, fetch, fetch_details
    n, d = fetch(con)
    d += fetch_details(con, 150)                                       # rules and broadcast systems of the mining / delivery / insurance jobs, a batch per run
    frac = (LAST.get("new", 0) + LAST.get("gone", 0)) / float(max(LAST.get("total", n), 1))
    return f"{n} jobs, {LAST.get('new', 0)} new, {LAST.get('gone', 0)} gone, {d} details", frac, LAST.get("expires")


def _incursions(con):
    from .esi import ESI
    from .incursions import fetch
    return fetch(con, ESI(timeout=20))


# id, label, start hours between runs, fastest, slowest, function
GRABS = [("freelance", "Freelance Jobs (ESI, public; about 4,500 jobs worldwide, a pull takes ~2 min)", 6.0, 1.0, 48.0, _freelance),
         ("incursions", "Incursions (ESI, public; a handful of Sansha incursions)", 1.0, 1.0, 12.0, _incursions)]


def _ts(con, gid):
    try:
        r = con.execute("SELECT value FROM meta WHERE key=?", ("grab_ts_" + gid,)).fetchone()
        return float(r[0]) if r else 0.0
    except Exception:                                                   # noqa: BLE001
        return 0.0


def _meta(con, key, default=None):
    try:
        r = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r[0] if r else default
    except Exception:                                                   # noqa: BLE001
        return default


def next_interval(iv, frac, lo, hi):
    """The more a list changes between pulls, the more often it is pulled; when it hardly changes, less often (never outside lo..hi hours)."""
    if frac >= 0.2:
        return max(lo, iv / 2.0)
    if frac < 0.05:
        return min(hi, iv * 1.5)
    return iv


def run_due(con, force=False):
    """Run the grabs whose time has come (their own adaptive interval AND ESI's cache end). -> list of result lines."""
    from email.utils import parsedate_to_datetime
    out, now = [], time.time()
    for gid, label, start_h, lo, hi, fn in GRABS:
        iv = float(_meta(con, "grab_int_" + gid, start_h))
        if not force and (now - _ts(con, gid) < iv * 3600.0 or now < float(_meta(con, "grab_exp_" + gid, 0))):
            continue
        try:
            res = fn(con)
            text, frac, exp = res if isinstance(res, tuple) else (res, 0.1, None)
            con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", ("grab_ts_" + gid, str(now)))
            new_iv = next_interval(iv, frac, lo, hi)
            con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", ("grab_int_" + gid, str(new_iv)))
            try:
                if exp:
                    con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", ("grab_exp_" + gid, str(parsedate_to_datetime(exp).timestamp())))
            except Exception:                                           # noqa: BLE001
                pass
            con.commit()
            out.append(f"{label}: {text}  (next pull in about {new_iv:.1f} h)")
        except Exception as e:                                          # noqa: BLE001
            con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", ("grab_int_" + gid, str(min(hi, iv * 2.0))))     # failing: back off, do not hammer
            con.commit()
            out.append(f"{label}: failed ({type(e).__name__}: {str(e)[:120]}); backing off")
    return out
