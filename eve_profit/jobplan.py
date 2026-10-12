"""Freelance jobs as ISK per hour. For each nearby DeliverItem job: buy the item at the cheapest ask in reach (or use stock you already hold), carry what fits,
deliver it for the job's pay per unit; time = the round trip. The alternative for the same goods is shown too: the best buy order you could sell into
(near you, or the best remembered world price). MineOre jobs show what their bonus adds per hour of mining. Profit along the way (trades, agents,
cheap needs) is whatever tripplus.extras finds on the route."""
from .freelance import item_names, near
from .manufacturing import buy_cost
from .orders import load_books, sell_into_bids

DOCK_S = 120.0
TRADE_S = 120.0


def _type_ids(con, items):
    ids = []
    for vt, i in items:
        if vt == "item_type":
            ids.append(i)
        else:
            ids += [r[0] for r in con.execute("SELECT type_id FROM types WHERE group_id=?", (i,))]
    return ids


def options(con, g, p, max_jumps=5):
    """-> list of dicts sorted by ISK/hr (best first)."""
    jobs = near(con, g, p, max_jumps)
    if not jobs:
        return []
    cur = g.id_of(p.current_system)
    reach = g.reach(cur, max_jumps + 2, p.avoid_yellow)
    sells, buys = load_books(con, set(reach))
    vol = {r[0]: r[1] for r in con.execute("SELECT type_id,volume FROM types")}
    name = {r[0]: r[1] for r in con.execute("SELECT type_id,name FROM types")}
    stock = {r[0]: r[1] for r in con.execute("SELECT type_id,SUM(quantity) FROM inventory GROUP BY type_id")}
    try:
        from .sellplan import is_ore, ore_hold_m3
        orehold = ore_hold_m3(con, p)
    except Exception:                                                   # noqa: BLE001
        is_ore, orehold = (lambda n: False), 0
    out = []
    for j in jobs:
        if j["method"] == "MineOre":
            ore = ", ".join(item_names(con, j["items"])[:1])
            y = getattr(p, "mining_yield_m3_s", 0) or 0
            vols = [vol.get(t, 0) for t in _type_ids(con, j["items"]) if vol.get(t)]
            if y > 0 and vols:
                per_hr = y / min(vols) * 3600.0                           # units mined per hour
                out.append({"kind": "mine bonus", "job": j, "what": ore, "jumps": j["jumps"], "isk_hr": per_hr * j["per_unit"],
                            "note": f"+{j['per_unit']:.2f} ISK per unit mined on top of the ore sale (about {per_hr:,.0f} units per hour)"})
            continue
        if j["method"] != "DeliverItem" or not j["items"]:
            continue
        tids = [t for t in _type_ids(con, j["items"]) if t in sells or stock.get(t)]
        best = None
        for t in tids:
            v = vol.get(t) or 0.0
            if v <= 0:
                continue
            room = (max(p.cargo_m3, orehold) if is_ore(name.get(t, "")) else p.cargo_m3)
            units = int(room // v)
            cap_job = int(j["remaining_isk"] // max(j["per_unit"], 0.01))
            if j["cap_pp"]:
                units = min(units, int(j["cap_pp"]))
            units = min(units, cap_job)
            if units < 1:
                continue
            have = int(stock.get(t, 0))
            use_stock = min(have, units)
            buy_units = units - use_stock
            cost, ask_sys = 0.0, None
            if buy_units:
                cand = [(buy_cost(asks, buy_units), s) for s, asks in sells.get(t, {}).items() if reach.get(s) is not None and reach[s].jumps <= 2]
                cand = [c for c in cand if c[0] is not None]
                if not cand:
                    units, buy_units = use_stock, 0
                    if units < 1:
                        continue
                else:
                    cost, ask_sys = min(cand)
            if p.wallet_isk and cost > p.wallet_isk:
                continue
            revenue = units * j["per_unit"]
            alt = alt_stock = 0.0                                       # what the same goods would fetch from the best buy order near you
            for s, bids in buys.get(t, {}).items():
                if s in reach and reach[s].jumps <= 2:
                    alt = max(alt, sell_into_bids(bids, units, p.sales_tax)[1])
                    if use_stock:
                        alt_stock = max(alt_stock, sell_into_bids(bids, use_stock, p.sales_tax)[1])
            secs = 2 * j["jumps"] * p.jump_seconds + 2 * DOCK_S + TRADE_S
            net = revenue - cost
            gain = net - alt_stock                                      # stock you already own could be sold instead: only the EXTRA counts
            row = {"kind": "deliver", "job": j, "what": name.get(t, str(t)), "units": units, "jumps": j["jumps"], "revenue": revenue, "cost": cost, "net": net, "gain": gain,
                   "alt_sell": alt, "minutes": secs / 60.0, "isk_hr": gain * 3600.0 / secs, "from_stock": use_stock, "buy_at": g.name[ask_sys] if ask_sys else None}
            if best is None or row["isk_hr"] > best["isk_hr"]:
                best = row
        if best:
            out.append(best)
    out.sort(key=lambda r: -r["isk_hr"])
    return out


def report(con, g, p, max_jumps=5, top=12):
    rows = [r for r in options(con, g, p, max_jumps) if r["isk_hr"] > 0]
    if not rows:
        return "No nearby freelance job beats simply selling yet (jobs that lose money are hidden). More details arrive 150 per run:  python -m eve_profit grabs --all"
    L = [f"{'ISK/hr':>10} {'jumps':>5}  job"]
    for r in rows[:top]:
        j = r["job"]
        if r["kind"] == "mine bonus":
            L.append(f"{r['isk_hr']:>10,.0f} {r['jumps']:>5}  MINE {r['what']}: {r['note']} ({j['corp'][:20]})")
        else:
            L.append(f"{r['isk_hr']:>10,.0f} {r['jumps']:>5}  DELIVER {r['units']:,} x {r['what']}: pay {r['revenue']:,.0f}, cost {r['cost']:,.0f} ({'stock ' + str(r['from_stock']) if r['from_stock'] else 'buy at ' + str(r['buy_at'])})"
                     f" = {r['net']:,.0f} net, {r['gain']:,.0f} MORE than selling, in {r['minutes']:.0f} min ({j['corp'][:18]})")
    return "\n".join(L)
