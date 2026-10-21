"""A trade as ONE step at a time, like the haul: fly to where you buy (the destination is set in the game), BUY there (per-unit price, station name), then the
haul chain flies it to the buyer one jump at a time and sells. Cargo is invisible to `sync`, so the chain (meta 'haul_chain') remembers it."""
from .orders import load_books, walk_trade

PENDING = {}            # step text -> haul dict, so next_action can start the chain when this step wins


STATION = {}            # step headline -> station id, so `next` can set the in-game destination to that station


def _station(con, tid, sysid, is_buy, g):
    """-> (location id or 0, name) of the cheapest ask / best bid in the system. An NPC station missing from the local table is asked from ESI (public) and cached."""
    lid = 0
    try:
        r = con.execute("SELECT location_id FROM orders WHERE type_id=? AND system_id=? AND is_buy=? ORDER BY price " + ("DESC" if is_buy else "ASC") + " LIMIT 1",
                        (tid, sysid, is_buy)).fetchone()
        lid = int(r[0]) if r and r[0] else 0
        if lid:
            n = con.execute("SELECT name FROM stations WHERE station_id=?", (lid,)).fetchone()
            if n and n[0]:
                return lid, n[0]
            n = con.execute("SELECT name FROM structures WHERE structure_id=?", (lid,)).fetchone()
            if n and n[0]:
                return lid, n[0]
            if lid < 10 ** 12:
                from .esi import ESI
                d = ESI(timeout=8).get(f"/universe/stations/{lid}/")[0]
                con.execute("INSERT OR REPLACE INTO stations(station_id,system_id,name,corporation_id) VALUES(?,?,?,?)",
                            (lid, int(d.get("system_id", sysid)), d.get("name"), d.get("owner")))
                con.commit()
                return lid, d.get("name") or f"station {lid}"
    except Exception:                                                   # noqa: BLE001
        pass
    return lid, f"the market in {g.name[sysid]}"


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
    st_id, st_buy = _station(con, tid, a, 0, g)
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
        try:                                                            # so `stop` can put the bought stack into the stock now (ESI shows it only within an hour)
            from .invoverlay import remember_buy_step
            remember_buy_step(con, a, [(tid, sum(by_price.values()) or units)])
        except Exception:                                               # noqa: BLE001
            pass
        if st_id:
            STATION[text.split("\n", 1)[0]] = st_id
        return text
    hop, left = a, 0                                                    # the destination is only the NEXT system on the way, never the far end
    try:
        r = g.route(g.id_of(here), a, 60, p.avoid_yellow)
        hop, left = (r.path[1] if len(r.path) > 1 else a), r.jumps
    except Exception:                                                   # noqa: BLE001
        pass
    return "\n".join([f"STEP: FLY to {g.name[hop]}",
                      f"   DO ONLY THIS: fly to {g.name[hop]} and stop there. Then run  python -m eve_profit next  (it plans again from there).",
                      f"   LATER: {units:,} x {name}: " + "; ".join(f"buy {q:,} at {ask:,.0f} each" for ask, q in sorted(by_price.items())) + f" at {st_buy} in {g.name[a]} ({left} jumps from here)"])


def pending(text):
    return PENDING.get(text)


def first_step_line(text):
    """The 'STEP: ...' headline of a step text, also when the step sits inside the numbered command list (lines marked with '§')."""
    for ln in (text or "").split("\n"):
        t = ln.strip().lstrip("§").strip().replace(">> ", "").strip()
        if t.startswith("STEP:"):
            return t
    return (text or "").strip().split("\n", 1)[0].replace(">> ", "").strip()


def station_of(text):
    """The station id a 'STEP: BUY at <station>' step wants as the in-game destination (0 if unknown)."""
    return STATION.get(first_step_line(text), 0)


def fresh(con, g, p, o):
    """Ask ESI for the newest orders of this ONE item in both regions, then re-price the trade. -> the fresh Opportunity, None if it no longer pays
    (the order was taken / expired), or `o` itself when ESI cannot be reached (then the planner's last scan is all there is)."""
    import os
    d = o.detail or {}
    if "type_id" not in d or os.environ.get("EVE_NO_LIVE"):
        return o
    try:
        from .esi import ESI, refresh_item
        from .trade import find_trades
        regions = sorted({g.region[d["from_sys"]], g.region[d["to_sys"]]})
        refresh_item(con, ESI(timeout=12), regions, d["type_id"])
    except Exception:                                                   # noqa: BLE001
        return o
    for x in find_trades(con, g, p):
        xd = x.detail
        if xd.get("type_id") == d["type_id"] and xd.get("from_sys") == d["from_sys"] and xd.get("to_sys") == d["to_sys"]:
            return x
    return None
