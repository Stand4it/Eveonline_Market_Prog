"""`along --to X`: sell what you have in your current system's hangar at the best system ON THE WAY to X.
Items that sell best here are sold here (no carrying); the rest are carried, densest value per m3 first,
and sold at the best system along the safe route. Unsold items stay in the hangar."""
from .basis import cost_basis, stack_basis
from .orders import load_books, sell_into_bids
from .skills import order_slots


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
    basis = cost_basis(con)
    far = g.reach(cur, max(p.max_jumps * 5, 10), p.avoid_yellow)       # where a loss-making item could go instead
    _, far_buys = load_books(con, set(far))
    here, carried, losses = [], [], []
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
        cost, covered = stack_basis(basis, tid, qty)
        if covered:
            per_unit = cost / covered
            basis_for_best = per_unit * min(best[3], covered)       # what the units we could sell here cost you
            if best[0] < basis_for_best:
                # selling anywhere on this route would lose money: look further afield, otherwise hold
                alt = None
                for s2 in far:
                    sold2, net2 = sell_into_bids(far_buys.get(tid, {}).get(s2, []), qty, p.sales_tax)
                    if sold2 and (alt is None or net2 > alt[0]):
                        alt = (net2, s2, sold2)
                losses.append({"name": name.get(tid, tid), "qty": qty, "cost": cost, "best_here": best[0],
                               "alt": alt, "alt_name": g.name[alt[1]] if alt else None,
                               "alt_jumps": far[alt[1]].jumps if alt else None})
                continue
        if best[2] != 0 and (local is None or best[0] > local[0] * 1.03):
            carried.append({"tid": tid, "name": name.get(tid, tid), "sold": best[3], "net": best[0], "at": best[2],
                            "m3": best[3] * (vol.get(tid, 0) or 0.0001), "extra": best[0] - (local[0] if local else 0)})
        elif local:
            asks = sells.get(tid, {}).get(cur, [])
            listing = qty * asks[0][0] if asks else 0.0
            list_net = listing * (1 - p.broker_fee - p.sales_tax)
            list_it = listing > 0 and list_net > local[0] * 1.15            # listing must beat instant by >15% to be worth the wait
            here.append({"tid": tid, "name": name.get(tid, tid), "sold": local[3], "net": local[0], "qty": qty,
                         "listing": listing, "list_net": list_net, "advice": "LIST" if list_it else "SELL NOW",
                         "cost": cost, "covered": covered})
    slots = order_slots(con)
    listers = sorted([d for d in here if d["advice"] == "LIST"], key=lambda d: -(d["list_net"] - d["net"]))
    if slots is not None:
        for d in listers[slots:]:
            d["advice"] = "SELL NOW"; d["no_slot"] = True        # best gain per slot first; the rest go instantly
    carried.sort(key=lambda d: -(d["net"] / max(d["m3"], 1e-6)))
    room, load = p.cargo_m3, []
    for d in carried:                                   # fill the hold by value per m3
        units = min(d["sold"], int(room / max(d["m3"] / d["sold"], 1e-6) + 1e-9))
        if units <= 0:
            continue
        frac = units / d["sold"]
        load.append(dict(d, sold=units, net=d["net"] * frac, m3=d["m3"] * frac, extra=d["extra"] * frac))
        room -= d["m3"] * frac
    watch = []
    for s in path:
        ships = g.kills.get(s, 0)
        gk = getattr(g, "gank", {}).get(s, 0)
        watch.append({"name": g.name[s], "sec": g.sec[s], "kills": ships, "gank": gk,
                      "level": "DANGER" if g.is_hot(s) else ("CAUTION" if (g.is_yellow(s) or ships or gk) else "ok")})
    return {"watch": watch, "dock_known": bool(dock), "empty": n_here == 0, "here_name": p.current_system, "path": [g.name[s] for s in path], "sell_here": sorted(here, key=lambda d: -d["net"]),
            "slots": slots, "losses": losses, "carry": load, "used_m3": p.cargo_m3 - room, "jumps": route.jumps}


def _watch_lines(watch):
    """Where there may be a kill on the route: ships destroyed in the last hour (CCP) and hauler losses in 7 days (zKillboard)."""
    flagged = [w for w in watch if w["level"] != "ok"]
    if not flagged:
        return ["ROUTE WATCH: no recent kills or hauler losses on any system of this route (data may be stale: run `scan --live`"
                " and `zkill` for fresh numbers).", ""]
    L = ["ROUTE WATCH (kills in the last hour / hauler losses in 7 days / security):"]
    for w in flagged:
        L.append(f"   {w['level']:<8} {w['name']:<14} sec {w['sec']:.1f}   ships killed last hour: {w['kills']:<3} "
                 f"hauler losses 7d: {w['gank']}")
    L.append("   DANGER = avoid or wait; CAUTION = fly it awake, not on autopilot. Refresh with: scan --live  and  zkill")
    return L + [""]


def format_along(res):
    L = [f"Route: {' > '.join(res['path'])}  ({res['jumps']} jumps)", ""]
    L += _watch_lines(res.get("watch", []))
    if res.get("empty"):
        return "\n".join(L + [f"No items found in your {res['here_name']} hangar. Items inside your ship are invisible to the program.",
                              "Move them into the Item hangar (Ctrl+A in the ship's cargo, drag to Item hangar), then run:",
                              "   python -m eve_profit sync", "and run `along` again."])
    here = res["sell_here"]
    now_items = [d for d in here if d.get("advice") != "LIST"]
    list_items = [d for d in here if d.get("advice") == "LIST"]
    where = "the station you are docked at" if res.get("dock_known") else "any Hek station (dock unknown: check each buyer's station!)"
    L.append(f"IN {res['path'][0]}, buy orders at {where}: {sum(d['net'] for d in here):,.0f} ISK if everything sold instantly")
    L.append(f"PLAN: sell {len(now_items)} stacks now for {sum(d['net'] for d in now_items):,.0f} ISK; "
             f"list {len(list_items)} stacks for about {sum(d['list_net'] for d in list_items):,.0f} ISK after fees "
             f"(vs {sum(d['net'] for d in list_items):,.0f} instantly) - listing takes time and an order slot each")
    if res.get("slots") is not None:
        L.append(f"Market order slots from your skills: {res['slots']} (minus any orders you already have open - check the "
                 f"Market Orders window). The LIST stacks below are the best gain per slot; the rest are marked SELL NOW.")
    L.append(f"   {'qty':>10}   {'item':<30} {'sell now':>13} {'listed, after fees*':>20} {'advice':<9} {'you paid':>12}")
    for d in sorted(here, key=lambda d: -max(d['net'], d.get('list_net', 0)))[:20]:
        short = f" (only {d['sold']:,} of {d['qty']:,} have buyers)" if d["sold"] < d["qty"] else ""
        paid = f"{d['cost']:>12,.0f}" if d.get("covered") else f"{'(no record)':>12}"
        vd = f"  ~{d['vol_day']:,.0f}/day on the market" if d.get("vol_day") is not None else ""
        L.append(f"   {d['sold']:>10,} x {d['name']:<30} {d['net']:>13,.0f} {d.get('list_net', 0):>20,.0f} "
                 f"{d.get('advice', ''):<9} {paid}{short}{vd}" + ("  (no free slot)" if d.get("no_slot") else ""))
    L.append("   * after the broker fee and sales tax, assuming you list at the cheapest existing sell order; others may undercut you.")
    if res.get("losses"):
        L += ["", "DO NOT SELL AT A LOSS - these would sell below what you paid on this whole route:"]
        for d in res["losses"]:
            msg = (f"better buyer: {d['alt_name']} ({d['alt_jumps']} jumps) pays {d['alt'][0]:,.0f} vs your cost {d['cost']:,.0f}"
                   if d["alt"] and d["alt"][0] > d["cost"] else
                   f"no buyer within reach pays your cost; HOLD or list a sell order above {d['cost'] / max(d['qty'], 1):,.0f} each")
            L.append(f"   {d['qty']:>10,} x {d['name']:<32} paid {d['cost']:>12,.0f}, best here {d['best_here']:>12,.0f} -> {msg}")
    L += ["", f"CARRY ({res['used_m3']:,.0f} m3) and sell on the way:"]
    by = {}
    for d in res["carry"]:
        by.setdefault(d["at"], []).append(d)
    for i in sorted(by):
        tot = sum(d["net"] for d in by[i])
        L.append(f"  at {res['path'][i]} (jump {i}): {tot:,.0f} ISK  (+{sum(d['extra'] for d in by[i]):,.0f} vs selling at the start)")
        for d in sorted(by[i], key=lambda d: -d["net"])[:10]:
            L.append(f"   {d['sold']:>10,} x {d['name']:<32} {d['net']:>12,.0f}   {d['m3']:,.0f} m3")
    if not by:
        L.append("   nothing sells better along the way; sell it all at the start.")
    return "\n".join(L)


def attach_history(esi, res, region_id, days=30, cap=12):
    """Daily traded volume for LIST candidates (public ESI history) so you can see if listing will actually sell."""
    n = 0
    for d in res["sell_here"]:
        if d.get("advice") != "LIST" or n >= cap:
            continue
        try:
            rows = esi.get(f"/markets/{region_id}/history/", type_id=d["tid"])[0][-days:]
        except Exception:
            continue
        n += 1
        if rows:
            d["vol_day"] = sum(r.get("volume", 0) for r in rows) / len(rows)
            d["days_to_sell"] = d["qty"] / d["vol_day"] if d["vol_day"] else None
    return res
