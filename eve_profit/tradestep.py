"""A trade as ONE step at a time, like the haul: fly to where you buy (the destination is set in the game), BUY there (per-unit price, station name), then the
haul chain flies it to the buyer one jump at a time and sells. Cargo is invisible to `sync`, so the chain (meta 'haul_chain') remembers it."""
from .orders import load_books, walk_trade

PENDING = {}            # step text -> haul dict, so next_action can start the chain when this step wins


def _station(con, tid, sysid, is_buy, g):
    try:
        r = con.execute("SELECT location_id FROM orders WHERE type_id=? AND system_id=? AND is_buy=? ORDER BY price " + ("DESC" if is_buy else "ASC") + " LIMIT 1",
                        (tid, sysid, is_buy)).fetchone()
        if r and r[0]:
            n = con.execute("SELECT name FROM stations WHERE station_id=?", (r[0],)).fetchone()
            if n and n[0]:
                return n[0]
            n = con.execute("SELECT name FROM structures WHERE structure_id=?", (r[0],)).fetchone()
            if n and n[0]:
                return n[0]
    except Exception:                                                   # noqa: BLE001
        pass
    return f"the market in {g.name[sysid]}"


def trade_step(con, g, p, o):
    """-> step text for a trade Opportunity (kind 'trade'), or None if it lacks the detail."""
    d = o.detail or {}
    if "from_sys" not in d or "to_sys" not in d:
        return None
    a, b, tid, units = d["from_sys"], d["to_sys"], d["type_id"], d["units"]
    name = {r[0]: r[1] for r in con.execute("SELECT type_id,name FROM types WHERE type_id=?", (tid,))}.get(tid, str(tid))
    sells, buys = load_books(con, {a, b})
    trace = []
    walk_trade(sells.get(tid, {}).get(a, []), buys.get(tid, {}).get(b, []), units, p.wallet_isk, p.sales_tax, trace)
    by_price = {}
    for take, ask, _ in trace:
        by_price[ask] = by_price.get(ask, 0) + take
    st_buy = _station(con, tid, a, 0, g)
    buy_lines = [f"   buy {q:,} x {name} at {ask:,.0f} each ({q * ask:,.0f} ISK)" for ask, q in sorted(by_price.items())] or [f"   buy {units:,} x {name}"]
    item = f"      {units:,} x {name}"
    top = max(by_price) if by_price else 0
    here = p.current_system
    h = {"dest": g.name[b], "jumps": 0, "gain": float(o.net_isk), "net": float(o.net_isk + d.get("cost", 0)),
         "items": [(name, units, float(o.net_isk + d.get("cost", 0)), 0.0)], "ore": False}
    try:
        h["jumps"] = g.route(a, b, 60, p.avoid_yellow).jumps
    except Exception:                                                   # noqa: BLE001
        pass
    if g.name[a] == here:
        text = "\n".join([f"STEP: BUY at {st_buy}", item] + buy_lines
                         + [f"   DO ONLY THIS: dock at {st_buy}, open Market, search {name}, buy {units:,} at the lowest sell orders (price per unit above; stop if it is above {top * 1.05:,.0f} each).",
                            "   Then run  python -m eve_profit next  (it flies your cargo on, one jump at a time)."])
        PENDING[text] = h
        return text
    jumps = ""
    try:
        jumps = f" ({g.route(g.id_of(here), a, 60, p.avoid_yellow).jumps} jumps)"
    except Exception:                                                   # noqa: BLE001
        pass
    return "\n".join([f"STEP: FLY to {g.name[a]}", item] + buy_lines + [f"   at {st_buy}",
                      f"   DO ONLY THIS: fly to {g.name[a]}{jumps} and dock at {st_buy}. Then run  python -m eve_profit next  (it gives the BUY step there)."])


def pending(text):
    return PENDING.get(text)
