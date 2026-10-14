"""Hangar changes you made that ESI does not show yet (the assets list is cached for about an hour): a SOLD stack stays in `inventory` after the sale, so the
sell step repeated. `remember_sell_step` stores what the SELL step listed; `confirm_sold` (on `stop`/`done` of that step) takes it out of inventory now and keeps it
out after every `sync` as long as ESI still returns the OLD asset list (same fingerprint)."""
import hashlib
import json
import time

MAX_AGE_S = 2 * 3600


def _sig(con):
    rows = con.execute("SELECT type_id,system_id,quantity FROM inventory ORDER BY 1,2").fetchall()
    return hashlib.md5(json.dumps([tuple(r) for r in rows]).encode()).hexdigest()


def _get(con, key):
    try:
        r = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(r[0]) if r else None
    except Exception:                                                   # noqa: BLE001
        return None


def _put(con, key, val):
    con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, json.dumps(val)))


def remember_sell_step(con, system_id, items):
    """items: [(type_id, qty)] the SELL NOW step asked you to sell here."""
    try:
        _put(con, "last_sell_step", {"sid": system_id, "items": [[int(t), int(q)] for t, q in items], "t": time.time()})
        con.commit()
    except Exception:                                                   # noqa: BLE001
        pass


def _subtract(con, sid, items):
    for tid, qty in items:
        con.execute("UPDATE inventory SET quantity=quantity-? WHERE type_id=? AND system_id=?", (qty, tid, sid))
    con.execute("DELETE FROM inventory WHERE quantity<=0")


def confirm_sold(con):
    """`stop` on a 'Market sell stock' run: take the listed stacks out of inventory now and remember them against the current (old) asset fingerprint. -> text."""
    st = _get(con, "last_sell_step")
    if not st or time.time() - st["t"] > MAX_AGE_S:
        return ""
    raw = _sig(con)
    _put(con, "pending_sold", {"sig": raw, "sid": st["sid"], "items": st["items"], "t": time.time()})
    _subtract(con, st["sid"], st["items"])
    _put(con, "last_sell_step", None)
    con.commit()
    names = []
    for tid, q in st["items"]:
        try:
            r = con.execute("SELECT name FROM types WHERE type_id=?", (tid,)).fetchone()
        except Exception:                                               # noqa: BLE001
            r = None
        names.append(f"{q:,} x {r[0] if r else tid}")
    return (f"Noted: taken out of your stock now: {'; '.join(names)} (ESI shows the real hangar within about an hour). "
            f"Did you keep one? run  python -m eve_profit done --goal \"kept NAME\"  to put it back.")


def after_sync(con):
    """Called by sync right after inventory was rebuilt from ESI: if ESI still returned the old list, keep the sold stacks out; else forget the pending sale."""
    p = _get(con, "pending_sold")
    if not p:
        return
    if time.time() - p["t"] > MAX_AGE_S or _sig(con) != p["sig"]:
        _put(con, "pending_sold", None)                                # fresh data (or too old): the real hangar wins
        return
    _subtract(con, p["sid"], p["items"])


def restore(con, name):
    """`done --goal "kept NAME"`: that stack was NOT sold after all: put it back into inventory and out of the pending sale. -> text."""
    p = _get(con, "pending_sold")
    if not p:
        return "Nothing is pending: the stock already matches the game (or the sale note is older than 2 hours)."
    keep, back = [], None
    for tid, q in p["items"]:
        try:
            r = con.execute("SELECT name FROM types WHERE type_id=?", (tid,)).fetchone()
        except Exception:                                               # noqa: BLE001
            r = None
        if r and name.strip().lower() in r[0].lower() and back is None:
            back = (tid, q, r[0])
        else:
            keep.append([tid, q])
    if not back:
        return f"No pending sale matches '{name}'."
    tid, q, nm = back
    con.execute("INSERT INTO inventory VALUES(?,?,?) ON CONFLICT(type_id,system_id) DO UPDATE SET quantity=quantity+excluded.quantity", (tid, p["sid"], q))
    p["items"] = keep
    _put(con, "pending_sold", p)
    con.commit()
    return f"OK, {q:,} x {nm} is back in your stock."
