"""Everything the tool can read from the game by program, on its own schedule. `now` runs every grab that is DUE (so market prices and these stay fresh
together); a one-off need is a step in `next` instead. Add a grab: one entry in GRABS (id, label, hours between runs, function(con) -> one-line result)."""
import time


def _freelance(con):
    from .freelance import fetch
    n, d = fetch(con)
    return f"{n} jobs, {d} new details"


GRABS = [("freelance", "Freelance Jobs (ESI, public)", 1.0, _freelance)]


def _ts(con, gid):
    try:
        r = con.execute("SELECT value FROM meta WHERE key=?", ("grab_ts_" + gid,)).fetchone()
        return float(r[0]) if r else 0.0
    except Exception:                                                   # noqa: BLE001
        return 0.0


def run_due(con, force=False):
    """Run the grabs whose time has come. -> list of result lines."""
    out, now = [], time.time()
    for gid, label, every_h, fn in GRABS:
        if not force and now - _ts(con, gid) < every_h * 3600.0:
            continue
        try:
            res = fn(con)
            con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", ("grab_ts_" + gid, str(now)))
            con.commit()
            out.append(f"{label}: {res}")
        except Exception as e:                                          # noqa: BLE001
            out.append(f"{label}: failed ({type(e).__name__}: {str(e)[:120]})")
    return out
