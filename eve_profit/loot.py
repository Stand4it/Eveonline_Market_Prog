"""Loot counts toward a mission's ISK/hr: the stuff you picked up is valued at what it would really sell for,
minus the cost of the time it takes to get it to a better market, and that travel time is added to the mission's hours.
Items only count once they are in a station hangar (the program cannot see inside your ship's cargo)."""
from .journey import TIME_VALUE_ISK_HR
from .orders import load_books, sell_into_bids

DOCK_MIN = 2.0


def snapshot(con):
    return {f"{t}:{s}": q for t, s, q in con.execute("SELECT type_id,system_id,quantity FROM inventory")}


def gains(before, after):
    """[(type_id, system_id, units gained)] for stacks that grew since the snapshot."""
    out = []
    for k, q in after.items():
        d = q - before.get(k, 0)
        if d > 0:
            t, s = k.split(":")
            out.append((int(t), int(s), d))
    return out


def value_loot(con, g, p, gain_rows, rate=TIME_VALUE_ISK_HR, radius=6):
    """-> dict(value, travel_hours, where, rows). Sell at the loot's own system, or make ONE side trip to the best nearby
    market if the extra ISK beats the time it costs (round trip, valued at `rate` ISK/hr)."""
    if not gain_rows:
        return {"value": 0.0, "travel_hours": 0.0, "where": None, "rows": [], "here": 0.0}
    cur = g.id_of(p.current_system)
    reach = g.reach(cur, radius, p.avoid_yellow)
    sells, buys = load_books(con, set(reach) | {s for _, s, _ in gain_rows})
    name = {r[0]: r[1] for r in con.execute("SELECT type_id,name FROM types")}
    here_net, rows = {}, []
    for tid, sysid, qty in gain_rows:
        sold, net = sell_into_bids(buys.get(tid, {}).get(sysid, []), qty, p.sales_tax)
        here_net[(tid, sysid)] = net
        rows.append({"tid": tid, "name": name.get(tid, tid), "qty": qty, "here": net})
    base = sum(here_net.values())
    best = (0.0, None, 0.0, {})                 # extra ISK after time cost, system, travel hours, per-stack nets
    for d, route in reach.items():
        if d == cur or route.jumps == 0:
            continue
        hours = (2 * route.jumps * p.jump_seconds / 60.0 + DOCK_MIN) / 60.0
        nets, extra = {}, 0.0
        for tid, sysid, qty in gain_rows:
            sold, net = sell_into_bids(buys.get(tid, {}).get(d, []), qty, p.sales_tax)
            nets[(tid, sysid)] = net
            extra += max(0.0, net - here_net[(tid, sysid)])
        gain = extra - rate * hours
        if gain > best[0]:
            best = (gain, d, hours, nets)
    gain, d, hours, nets = best
    if d is None:
        return {"value": base, "travel_hours": 0.0, "where": None, "rows": rows, "here": base}
    for r in rows:
        r["there"] = nets[(r["tid"], next(s for t, s, _ in gain_rows if t == r["tid"]))]
    total = sum(max(r["here"], r.get("there", 0.0)) for r in rows)
    return {"value": total, "travel_hours": hours, "where": g.name[d], "rows": rows, "here": base,
            "jumps": reach[d].jumps}


def describe(res, rate=TIME_VALUE_ISK_HR):
    if not res["rows"]:
        return ["   (no new items found in your station hangars)"]
    L = [f"   loot value {res['value']:,.0f} ISK"
         + (f"; best to sell at {res['where']} ({res['jumps']} jumps each way, {res['travel_hours'] * 60:.0f} min round trip "
            f"counted in the hours; sold here instead would be {res['here']:,.0f})" if res["where"] else " (sold at the station you are in)")]
    for r in sorted(res["rows"], key=lambda r: -max(r["here"], r.get("there", 0)))[:6]:
        L.append(f"      {r['qty']:>8,} x {r['name']:<30} {max(r['here'], r.get('there', 0)):>12,.0f}")
    return L
