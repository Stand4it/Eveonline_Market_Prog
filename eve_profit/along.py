"""`along --to X`: sell what you have in your current system's hangar at the best system ON THE WAY to X.
Items that sell best here are sold here (no carrying); the rest are carried, densest value per m3 first,
and sold at the best system along the safe route. Unsold items stay in the hangar."""
from .orders import load_books, sell_into_bids


def _bids_at(con, location_id):
    out = {}
    for r in con.execute("SELECT type_id,price,volume_remain,min_volume FROM orders WHERE location_id=? AND is_buy=1 "
                         "ORDER BY price DESC", (location_id,)):
        out.setdefault(r["type_id"], []).append((r["price"], r["volume_remain"], r["min_volume"]))
    return out


def plan_along(con, g, p, dest_name):
    cur = g.id_of(p.current_system)
    route = g.route(cur, g.id_of(dest_name), 60, p.avoid_yellow)
    if route is None:
        raise ValueError(f"no safe route from {p.current_system} to {dest_name}")
    path = route.path
    vol = {r[0]: r[1] for r in con.execute("SELECT type_id,volume FROM types")}
    name = {r[0]: r[1] for r in con.execute("SELECT type_id,name FROM types")}
    sells, buys = load_books(con, set(path))
    dock = p.current_location_id
    dock_bids = _bids_at(con, dock) if dock else None        # {type_id: [(price, vol, min)]} at YOUR station only
    here, carried = [], []
    n_here = con.execute("SELECT COUNT(*) FROM inventory WHERE system_id=?", (cur,)).fetchone()[0]
    for r in con.execute("SELECT type_id,quantity FROM inventory WHERE system_id=?", (cur,)).fetchall():
        tid, qty = r["type_id"], r["quantity"]
        opts = []
        for i, s in enumerate(path):
            bids = dock_bids.get(tid, []) if (i == 0 and dock_bids is not None) else buys.get(tid, {}).get(s, [])
            sold, net = sell_into_bids(bids, qty, p.sales_tax)
            if sold:
                opts.append((net, -i, i, sold))
        if not opts:
            continue
        best = max(opts)
        local = next((o for o in opts if o[2] == 0), None)
        # carry only if it clearly beats selling here (>3%), else sell here and travel light
        if best[2] != 0 and (local is None or best[0] > local[0] * 1.03):
            carried.append({"tid": tid, "name": name.get(tid, tid), "sold": best[3], "net": best[0], "at": best[2],
                            "m3": best[3] * (vol.get(tid, 0) or 0.0001), "extra": best[0] - (local[0] if local else 0)})
        elif local:
            asks = sells.get(tid, {}).get(cur, [])
            listing = qty * asks[0][0] if asks else 0.0
            here.append({"tid": tid, "name": name.get(tid, tid), "sold": local[3], "net": local[0], "qty": qty,
                         "listing": listing})
    carried.sort(key=lambda d: -(d["net"] / max(d["m3"], 1e-6)))
    room, load = p.cargo_m3, []
    for d in carried:                                   # fill the hold by value per m3
        units = min(d["sold"], int(room / max(d["m3"] / d["sold"], 1e-6) + 1e-9))
        if units <= 0:
            continue
        frac = units / d["sold"]
        load.append(dict(d, sold=units, net=d["net"] * frac, m3=d["m3"] * frac, extra=d["extra"] * frac))
        room -= d["m3"] * frac
    return {"dock_known": bool(dock), "empty": n_here == 0, "here_name": p.current_system, "path": [g.name[s] for s in path], "sell_here": sorted(here, key=lambda d: -d["net"]),
            "carry": load, "used_m3": p.cargo_m3 - room, "jumps": route.jumps}


def format_along(res):
    L = [f"Route: {' > '.join(res['path'])}  ({res['jumps']} jumps)", ""]
    if res.get("empty"):
        return "\n".join(L + [f"No items found in your {res['here_name']} hangar. Items inside your ship are invisible to the program.",
                              "Move them into the Item hangar (Ctrl+A in the ship's cargo, drag to Item hangar), then run:",
                              "   python -m eve_profit sync", "and run `along` again."])
    here = res["sell_here"]
    where = "the station you are docked at" if res.get("dock_known") else "any Hek station (dock unknown: check each buyer's station!)"
    L.append(f"SELL IN {res['path'][0]} - into buy orders at {where}: {sum(d['net'] for d in here):,.0f} ISK instantly")
    L.append(f"   {'qty':>10}   {'item':<32} {'sell now':>14} {'if listed*':>14}")
    for d in here[:15]:
        short = f" (only {d['sold']:,} of {d['qty']:,} have buyers)" if d["sold"] < d["qty"] else ""
        L.append(f"   {d['sold']:>10,} x {d['name']:<32} {d['net']:>14,.0f} {d['listing']:>14,.0f}{short}")
    L.append("   * 'if listed' = quantity x the cheapest existing sell order, BEFORE broker fee, sales tax and waiting; real result is lower.")
    by = {}
    for d in res["carry"]:
        by.setdefault(d["at"], []).append(d)
    L += ["", f"CARRY ({res['used_m3']:,.0f} m3) and sell on the way:"]
    for i in sorted(by):
        tot = sum(d["net"] for d in by[i])
        L.append(f"  at {res['path'][i]} (jump {i}): {tot:,.0f} ISK  (+{sum(d['extra'] for d in by[i]):,.0f} vs selling at the start)")
        for d in sorted(by[i], key=lambda d: -d["net"])[:10]:
            L.append(f"   {d['sold']:>10,} x {d['name']:<32} {d['net']:>12,.0f}   {d['m3']:,.0f} m3")
    if not by:
        L.append("   nothing sells better along the way; sell it all at the start.")
    return "\n".join(L)
