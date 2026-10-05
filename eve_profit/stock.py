"""`stock`: what you own (stations/hangars), what it is worth if sold to buy orders near it, and where."""
from .orders import load_books, sell_into_bids


def stock_report(con, g, p, top=25):
    vol = {r[0]: r[1] for r in con.execute("SELECT type_id,volume FROM types")}
    name = {r[0]: r[1] for r in con.execute("SELECT type_id,name FROM types")}
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
            rows.append((best[1], name.get(tid, tid), qty, best[2], g.name[sid], g.name[best[0]], best[3], m3))
        else:
            unpriced.append((name.get(tid, tid), qty, g.name[sid]))
    rows.sort(reverse=True)
    L = [f"Stock in stations/structures: {len(rows) + len(unpriced)} stacks, "
         f"{total:,.0f} ISK if sold now into nearby buy orders (after tax).", "",
         f"{'ISK if sold':>14}  {'item':<34} {'qty':>10} {'sellable':>9} {'m3':>9}  {'where it is':<12} -> best buyer (jumps)"]
    for net, n, qty, sold, at, to, j, m3 in rows[:top]:
        L.append(f"{net:>14,.0f}  {str(n)[:34]:<34} {qty:>10,} {sold:>9,} {m3:>9,.0f}  {at:<12} -> {to} ({j})")
    if unpriced:
        L += ["", f"No buy orders in range for {len(unpriced)} stacks (e.g. SKINs, special items): " +
              ", ".join(f"{n} x{q:,} @ {s}" for n, q, s in unpriced[:8])]
    L += ["", "Note: only items in station/structure hangars are counted. Items inside your ship's cargo or other"
              " containers are not visible to the program - stash them in the hangar, then run `sync`."]
    return "\n".join(L)
