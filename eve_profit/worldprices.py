"""Worldwide prices, remembered. `now`, `bestprice` and `sellplan --world` look at the best buyers in ALL of New Eden for a stack; the answer used to be
printed and forgotten. Now the best markets are stored (world_prices) so `next` can see that a light, valuable item pays several times more far away
than here, and KEEP it (hangar, or your ship's hold) until a trip passes the good buyer, instead of dumping it cheaply nearby."""
import time

HOLD_MIN_RATIO = 2.0         # the far market pays at least this many times what you get nearby
HOLD_MIN_EXTRA = 50_000.0    # ... and at least this many ISK more
HOLD_MAX_M3 = 100.0          # ... and the stack is light enough to carry along without a second thought
MAX_AGE_DAYS = 7.0           # prices older than this are not trusted
KEEP_ROWS = 6


def save(con, tid, rows):
    """Remember the best markets for one item (rows from bestprice.best_prices, best first)."""
    try:
        con.execute("DELETE FROM world_prices WHERE type_id=?", (tid,))
        now = time.time()
        con.executemany("INSERT INTO world_prices VALUES(?,?,?,?,?,?,?)",
                        [(tid, d["system"], float(d["net"]), int(d.get("units") or 0), d.get("jumps"), int(d.get("gank") or 0), now) for d in rows[:KEEP_ROWS] if d.get("units")])
        con.commit()
    except Exception:                                                   # noqa: BLE001
        pass


def best_far(con, tid, qty):
    """Best remembered market for qty units: {'system','net','jumps','gank','age_days'} or None. Net is scaled to qty (up to the units that market could take)."""
    try:
        rows = con.execute("SELECT system, net, units, jumps, gank, ts FROM world_prices WHERE type_id=? AND jumps IS NOT NULL", (tid,)).fetchall()
    except Exception:                                                   # noqa: BLE001
        return None
    best = None
    for r in rows:
        if not r["units"] or (time.time() - r["ts"]) / 86400.0 > MAX_AGE_DAYS:
            continue
        net = r["net"] * min(qty, r["units"]) / r["units"]
        if best is None or net > best["net"]:
            best = {"system": r["system"], "net": net, "jumps": r["jumps"], "gank": r["gank"], "age_days": (time.time() - r["ts"]) / 86400.0}
    return best


def hold_advice(con, tid, qty, volume_each, local_net):
    """When a light stack pays several times more at a far market than the best you can get nearby: -> dict(system, net, jumps, extra) else None."""
    if qty <= 0 or (qty * (volume_each or 0.0)) > HOLD_MAX_M3:
        return None
    far = best_far(con, tid, qty)
    if not far:
        return None
    if far["net"] >= HOLD_MIN_RATIO * max(local_net, 1.0) and far["net"] - local_net >= HOLD_MIN_EXTRA:
        return {**far, "extra": far["net"] - local_net, "local": local_net}
    return None


def keep_line(name, qty, adv):
    return (f"keep {qty:,} x {name}: pays ~{adv['net']:,.0f} at {adv['system']} ({adv['jumps']} jumps) against ~{adv['local']:,.0f} nearby: carry it until a trip passes there"
            + (f" [{adv['gank']} recent ganks there]" if adv.get("gank") else ""))
