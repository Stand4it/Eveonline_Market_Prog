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


def remember_buy_step(con, system_id, items):
    """items: [(type_id, qty)] the BUY step asked you to buy here."""
    try:
        _put(con, "last_buy_step", {"sid": system_id, "items": [[int(t), int(q)] for t, q in items], "t": time.time()})
        con.commit()
    except Exception:                                                   # noqa: BLE001
        pass


def _add(con, sid, items):
    for tid, qty in items:
        r = con.execute("UPDATE inventory SET quantity=quantity+? WHERE type_id=? AND system_id=?", (qty, tid, sid))
        if r.rowcount == 0:
            con.execute("INSERT INTO inventory(type_id,system_id,quantity) VALUES(?,?,?)", (tid, sid, qty))


def confirm_bought(con):
    """`stop` on a 'Trade: buy at' run: the items the BUY step listed are in your hangar NOW (ESI shows them within about an hour): add them to inventory so the buy step is not offered
    again, and keep them there after every `sync` while ESI still returns the OLD asset list. -> text."""
    st = _get(con, "last_buy_step")
    if not st or time.time() - st["t"] > MAX_AGE_S:
        return ""
    _put(con, "pending_bought", {"sig": _sig(con), "sid": st["sid"], "items": st["items"], "t": time.time()})
    _add(con, st["sid"], st["items"])
    _put(con, "last_buy_step", None)
    con.commit()
    names = []
    for tid, q in st["items"]:
        r = con.execute("SELECT name FROM types WHERE type_id=?", (tid,)).fetchone()
        names.append(f"{q:,} x {r[0] if r else tid}")
    return (f"Noted: added to your stock now: {'; '.join(names)} (ESI shows the real hangar within about an hour). "
            f"Did you buy fewer? run  python -m eve_profit done --goal \"bought less\"  is not needed: the next sync corrects it.")


def after_sync(con):
    """Called by sync right after inventory was rebuilt from ESI: if ESI still returned the old list, keep the sold stacks out; else forget the pending sale."""
    pb = _get(con, "pending_bought")
    if pb:
        if time.time() - pb["t"] > MAX_AGE_S or _sig(con) != pb["sig"]:
            _put(con, "pending_bought", None)                          # fresh data (or too old): the real hangar wins
        else:
            _add(con, pb["sid"], pb["items"])                          # ESI still shows the old list: the bought stack stays in
    p = _get(con, "pending_sold")
    if not p:
        return
    if time.time() - p["t"] > MAX_AGE_S or _sig(con) != p["sig"]:
        _put(con, "pending_sold", None)                                # fresh data (or too old): the real hangar wins
        return
    _subtract(con, p["sid"], p["items"])


def mark_opened(con, name, qty=1):
    """`done --goal "opened NAME"`: you opened a crate (or used up an item) in the game: take it out of the stock NOW and keep it out after every `sync`
    while ESI still returns the old asset list (same rule as a sale). What came out of it shows up by itself once ESI refreshes (about an hour). -> text."""
    rows = con.execute("SELECT i.type_id, i.system_id, i.quantity, t.name FROM inventory i JOIN types t ON t.type_id=i.type_id "
                       "WHERE t.name LIKE ? COLLATE NOCASE ORDER BY (LOWER(t.name)=LOWER(?)) DESC, i.quantity DESC", (f"%{name.strip()}%", name.strip())).fetchall()
    if not rows:
        return f"No item matching '{name}' is in your stock (already gone, or a typo)."
    if len({r[3] for r in rows}) > 1 and rows[0][3].lower() != name.strip().lower():
        return "More than one item matches: " + "; ".join(sorted({r[3] for r in rows})) + ". Use the full name."
    tid, sid, have, nm = rows[0]
    q = min(qty, have)
    p = _get(con, "pending_sold")
    if p and time.time() - p["t"] <= MAX_AGE_S and p.get("sid") == sid:
        p["items"].append([tid, q])                                      # the stock already has this pending change applied; add to it
        p["t"] = time.time()
    else:
        p = {"sig": _sig(con), "sid": sid, "items": [[tid, q]], "t": time.time()}
    _put(con, "pending_sold", p)
    _subtract(con, sid, [[tid, q]])
    con.commit()
    return (f"Noted: {q:,} x {nm} is out of your stock now (opened/used). What came out of it appears after a sync once ESI refreshes (within about an hour). "
            f"Log what was inside to learn whether opening pays:  python scripts/crate_log.py \"{nm}\" \"<item>\" [\"<item>\" ...]")


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
    hold_add(con, nm)                                                   # you kept it for a better price: do not offer it as a sale again
    return f"OK, {q:,} x {nm} is back in your stock and on your HOLD list (`next` will not offer to sell it; release with  done --goal \"release {nm}\")."


def hold_names(con):
    """Items you decided to HOLD for a better market (never offered as 'SELL NOW'): lower-case names."""
    return set(_get(con, "hold_items") or [])


def hold_add(con, name):
    names = hold_names(con)
    names.add(name.strip().lower())
    _put(con, "hold_items", sorted(names))
    con.commit()
    return f"OK, '{name.strip()}' is on your HOLD list: `next` will not offer it as a sale (release it with  done --goal \"release {name.strip()}\")."


def hold_release(con, name):
    names = {n for n in hold_names(con) if name.strip().lower() not in n}
    _put(con, "hold_items", sorted(names))
    con.commit()
    return f"OK, '{name.strip()}' is no longer on your HOLD list."
