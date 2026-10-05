"""`stock`: what you own (stations/hangars), what it is worth if sold to buy orders near it, and where."""
from .orders import load_books, sell_into_bids


FAR_JUMPS = 40     # how far (safe jumps) to look for your own stock


def stock_report(con, g, p, top=25):
    vol = {r[0]: r[1] for r in con.execute("SELECT type_id,volume FROM types")}
    name = {r[0]: r[1] for r in con.execute("SELECT type_id,name FROM types")}
    here = g.reach(g.id_of(p.current_system), FAR_JUMPS, p.avoid_yellow)
    rows, total, unpriced = [], 0.0, []
    for inv in con.execute("SELECT type_id,system_id,quantity FROM inventory").fetchall():
        tid, sid, qty = inv["type_id"], inv["system_id"], inv["quantity"]
        if sid not in g.adj:
            continue
        reach = g.reach(sid, p.max_jumps * 2, p.avoid_yellow)
        _, buys = load_books(con, reach)
        best = None
        for b, bids in buys.get(tid, {}).items():
            sold, net = sell_into_bids(bids, qty, p.sales_tax)
            if sold and (best is None or net > best[1]):
                best = (b, net, sold, reach[b].jumps)
        m3 = qty * (vol.get(tid, 0) or 0)
        if best:
            total += best[1]
            rows.append((best[1], name.get(tid, tid), qty, best[2], f"{g.name[sid]} ({here[sid].jumps}j)" if sid in here else f"{g.name[sid]} (far)", g.name[best[0]], best[3], m3))
        else:
            unpriced.append((name.get(tid, tid), qty, g.name[sid]))
    rows.sort(reverse=True)
    L = [f"Stock in stations/structures: {len(rows) + len(unpriced)} stacks, "
         f"{total:,.0f} ISK if sold now into nearby buy orders (after tax).", "",
         f"{'ISK if sold':>14}  {'item':<34} {'qty':>10} {'sellable':>9} {'m3':>9}  {'where it is (jumps from you)':<26} -> best buyer (jumps)"]
    for net, n, qty, sold, at, to, j, m3 in rows[:top]:
        L.append(f"{net:>14,.0f}  {str(n)[:34]:<34} {qty:>10,} {sold:>9,} {m3:>9,.0f}  {at:<26} -> {to} ({j})")
    if unpriced:
        L += ["", f"No buy orders in range for {len(unpriced)} stacks (e.g. SKINs, special items): " +
              ", ".join(f"{n} x{q:,} @ {s}" for n, q, s in unpriced[:8])]
    L += ["", format_loads(best_loads(con, g, p))]
    L += ["", "Note: only items in station/structure hangars are counted. Items inside your ship's cargo or other"
              " containers are not visible to the program - stash them in the hangar, then run `sync`."]
    return "\n".join(L)


def best_loads(con, g, p, top=3, max_sources=6):
    """For stock parked in a system: the best single hold-load to carry to ONE buyer, filled by value per m3.
    Time = trip from where you are to the stock + stock to buyer. -> list of dict, best ISK/hr first."""
    cur = g.id_of(p.current_system)
    from_cur = g.reach(cur, FAR_JUMPS, p.avoid_yellow)          # where is each pile relative to YOU
    vol = {r[0]: r[1] for r in con.execute("SELECT type_id,volume FROM types")}
    name = {r[0]: r[1] for r in con.execute("SELECT type_id,name FROM types")}
    by_sys = {}
    for r in con.execute("SELECT type_id,system_id,quantity FROM inventory"):
        if r["system_id"] in from_cur:
            by_sys.setdefault(r["system_id"], []).append((r["type_id"], r["quantity"]))
    sources = sorted(by_sys, key=lambda s: -len(by_sys[s]))[:max_sources]
    out = []
    for s in sources:
        reach_s = g.reach(s, p.max_jumps * 3, p.avoid_yellow)
        _, buys = load_books(con, reach_s)
        best = None
        for b, rt in reach_s.items():
            if b == s:
                continue
            cands = []
            for tid, qty in by_sys[s]:
                sold, net = sell_into_bids(buys.get(tid, {}).get(b, []), qty, p.sales_tax)
                if sold:
                    v = max(vol.get(tid, 0.0) or 0.0, 0.0001)
                    cands.append((net / sold / v, tid, sold, net, v))       # net ISK per m3
            cands.sort(reverse=True)
            room, total, items = p.cargo_m3, 0.0, []
            for dens, tid, sold, net, v in cands:
                units = min(sold, int(room // v))
                if units <= 0:
                    continue
                part = net * units / sold
                items.append((name.get(tid, tid), units, part))
                total += part
                room -= units * v
            if not items:
                continue
            trip = from_cur[s].jumps + rt.jumps
            hours = (trip * p.jump_seconds + 3 * p.dock_overhead_s + p.trade_overhead_s) / 3600
            cand = {"from": g.name[s], "to": g.name[b], "net": total, "items": items, "used": p.cargo_m3 - room,
                    "jumps": trip, "hours": hours, "isk_per_hour": total / hours,
                    "waypoints": from_cur[s].path[1:] + rt.path[1:]}
            if best is None or cand["isk_per_hour"] > best["isk_per_hour"]:
                best = cand
        if best:
            out.append(best)
    out.sort(key=lambda d: -d["isk_per_hour"])
    return out[:top]


def format_loads(loads):
    if not loads:
        return "No profitable hold-loads for the stock you own near here."
    L = ["Best hold-loads for your stock (filled by ISK per m3):"]
    for d in loads:
        L.append(f"\n  {d['from']} -> {d['to']}: {d['net']:,.0f} ISK, {d['used']:,.0f} m3 used, {d['jumps']} jumps, "
                 f"~{d['hours'] * 60:.0f} min, {d['isk_per_hour']:,.0f} ISK/hr")
        for n, u, v in d["items"][:8]:
            L.append(f"      {u:>9,} x {n:<30} {v:>12,.0f}")
    return "\n".join(L)
