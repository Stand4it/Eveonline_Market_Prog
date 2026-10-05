"""`bestprice --item NAME [--qty N]`: who pays the most for one item ANYWHERE in New Eden (public ESI, region by region),
what you would net for your quantity (order depth, after tax), and how far that is on a safe route from where you are.
A same-region view like the in-game market window can't show this; neither can a nearby-only scan."""
from .orders import sell_into_bids


def resolve_type(con, text):
    """Item name (case-insensitive) or numeric type id -> (type_id, name, volume)."""
    t = text.strip()
    row = (con.execute("SELECT type_id,name,volume FROM types WHERE type_id=?", (int(t),)).fetchone()
           if t.isdigit() else con.execute("SELECT type_id,name,volume FROM types WHERE name=? COLLATE NOCASE", (t,)).fetchone())
    if row is None:
        raise ValueError(f"unknown item '{text}' (use the exact in-game name or its type id)")
    return row["type_id"], row["name"], row["volume"] or 0.0


def all_regions(con):
    return [r[0] for r in con.execute("SELECT DISTINCT region_id FROM systems WHERE region_id>0 ORDER BY region_id")]


def best_prices(con, g, p, esi, type_id, qty, top=6, log=lambda *_: None):
    """-> list of dict(net, units, price, system, region, jumps, minutes, hours...) sorted by net, best first."""
    cur = g.id_of(p.current_system)
    book = {}                                           # (region, system, location) -> [(price, volume, min)]
    regions = all_regions(con)
    for n, rid in enumerate(regions, 1):
        try:
            rows = esi.paged(f"/markets/{rid}/orders/", order_type="buy", type_id=type_id)
        except Exception as e:                          # a region can fail (no market, ESI hiccup): skip it
            log(f"  region {rid}: {type(e).__name__}")
            continue
        for o in rows:
            sysid = o.get("system_id")
            if sysid in g.sec:
                book.setdefault((rid, sysid, o["location_id"]), []).append((o["price"], o["volume_remain"], o.get("min_volume", 1)))
        if n % 15 == 0:
            log(f"  checked {n}/{len(regions)} regions...")
    reach = g.reach(cur, 80, p.avoid_yellow)
    out = []
    for (rid, sysid, loc), bids in book.items():
        bids.sort(reverse=True)
        sold, net = sell_into_bids(bids, qty, p.sales_tax)
        if not sold:
            continue
        r = reach.get(sysid)
        out.append({"net": net, "units": sold, "avg": net / sold, "top_price": bids[0][0], "system": g.name[sysid],
                    "sec": g.sec[sysid], "region": rid, "location": loc,
                    "jumps": r.jumps if r else None,
                    "minutes": (r.jumps * p.jump_seconds / 60 + 2) if r else None,
                    "gank": getattr(g, "gank", {}).get(sysid, 0)})
    out.sort(key=lambda d: -d["net"])
    return out[:top * 3], cur


def format_best(name, qty, rows, here_name):
    if not rows:
        return f"No buy orders for {name} anywhere (or ESI returned nothing). Try again later."
    local = next((d for d in rows if d["system"] == here_name), None)
    L = [f"Best buyers for {qty:,} x {name} (net after sales tax, using order depth):", ""]
    L.append(f"   {'net ISK':>14} {'each':>10} {'sellable':>9} {'where':<14} {'sec':>4} {'jumps':>6} {'~min':>5}  vs here")
    for d in rows[:8]:
        gain = f"{d['net'] - local['net']:+,.0f}" if local else ""
        jumps = f"{d['jumps']}" if d["jumps"] is not None else "no safe route"
        mins = f"{d['minutes']:.0f}" if d["minutes"] is not None else ""
        warn = f"  GANKS x{d['gank']}!" if d["gank"] else ""
        L.append(f"   {d['net']:>14,.0f} {d['avg']:>10,.2f} {d['units']:>9,} {d['system']:<14} {d['sec']:>4.1f} {jumps:>6} {mins:>5}  {gain}{warn}")
    L.append("")
    best = rows[0]
    if local is not None and best["system"] != here_name and best["net"] > local["net"] * 1.05:
        L.append(f"=> {best['system']} pays {best['net'] - local['net']:,.0f} ISK more than {here_name} "
                 f"({(best['net'] / local['net'] - 1) * 100:.0f}%). Worth the trip only if that beats what you'd earn in the ~"
                 f"{(best['minutes'] or 0) * 2:.0f} min round trip: ISK/hr = {(best['net'] - local['net']) / max((best['minutes'] or 1) / 30, 0.1):,.0f} (one way + back).")
    elif local is not None:
        L.append(f"=> Selling here is within 5% of the best price in New Eden: just sell in {here_name}.")
    else:
        L.append("=> Nobody here is buying this; the best listed buyer is the first line.")
    return "\n".join(L)
