"""`buy --item NAME --qty N`: where to BUY an item cheapest near you (sell orders), for agent jobs that say 'acquire these goods'.
Public ESI, only the few regions around you; walks the order depth for your quantity; shows jumps and minutes."""
from .esi import refresh_item


def best_buys(con, g, p, esi, regions, type_id, qty, radius=10, refresh=True):
    if refresh and esi is not None:
        refresh_item(con, esi, regions, type_id)
    cur = g.id_of(p.current_system)
    reach = g.reach(cur, radius, p.avoid_yellow)
    by = {}
    for r in con.execute("SELECT system_id,location_id,price,volume_remain,min_volume FROM orders WHERE type_id=? AND is_buy=0 ORDER BY price", (type_id,)):
        if r["system_id"] in reach:
            by.setdefault((r["system_id"], r["location_id"]), []).append((r["price"], r["volume_remain"], r["min_volume"]))
    out = []
    for (sysid, loc), asks in by.items():
        got, cost = 0, 0.0
        for price, vol, minv in asks:
            take = min(vol, qty - got)
            if take <= 0:
                break
            got += take
            cost += take * price
        route = reach[sysid]
        out.append({"system": g.name[sysid], "sec": g.sec[sysid], "jumps": route.jumps, "units": got, "full": got >= qty,
                    "cost": cost, "each": cost / got if got else 0.0, "minutes": route.jumps * p.jump_seconds / 60.0 + 2,
                    "gank": getattr(g, "gank", {}).get(sysid, 0)})
    out.sort(key=lambda d: (not d["full"], d["cost"] + d["jumps"] * 50.0))
    return out


def format_buys(name, qty, rows, here):
    if not rows:
        return f"Nobody within reach sells {name}. Check the market in game, or build it (blueprint/minerals), or widen --radius."
    L = [f"Cheapest places to BUY {qty:,} x {name} near {here} (sell orders, order depth walked):", "",
         f"   {'total ISK':>12} {'each':>10} {'units':>8} {'where':<14} {'sec':>4} {'jumps':>5} {'~min':>5}"]
    for d in rows[:8]:
        warn = f"  GANKS x{d['gank']}!" if d["gank"] else ""
        part = "" if d["full"] else "  (only part available)"
        L.append(f"   {d['cost']:>12,.0f} {d['each']:>10,.2f} {d['units']:>8,} {d['system']:<14} {d['sec']:>4.1f} {d['jumps']:>5} {d['minutes']:>5.0f}{warn}{part}")
    full = [d for d in rows if d["full"]]
    if full:
        near = min(full, key=lambda d: d["jumps"])
        cheap = min(full, key=lambda d: d["cost"])
        L.append("")
        L.append(f"=> Nearest full order: {near['system']} ({near['jumps']} jumps) for {near['cost']:,.0f} ISK. "
                 f"Cheapest: {cheap['system']} ({cheap['jumps']} jumps) for {cheap['cost']:,.0f} ISK.")
        L.append("   Small jobs: take the nearest. Only travel for the cheapest if the saving is bigger than the time is worth.")
    return "\n".join(L)
