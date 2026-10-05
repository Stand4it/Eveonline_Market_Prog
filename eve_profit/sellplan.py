"""`sellplan`: for each stack you hold HERE, is it better to sell now, list, carry it along the trip you are already making,
detour to a nearby buyer, or haul to the best market anywhere?  Every option is scored by

    gain = (net ISK vs selling now) - (extra minutes x what your time is worth)

where your time is worth the ISK/hr of your best alternative task (top of `scan`). Carrying along a trip you make anyway costs
~2 minutes (dock + sell); a detour or a dedicated haul costs the round trip. Options that add under 2% are ignored (not worth
the hassle/risk); the hold size and the value you carry are respected."""
from .along import _bids_at
from .orders import load_books, sell_into_bids
import dataclasses

from .planner import plan
from .skills import order_slots

MIN_LIST_GAIN = 250_000.0     # a listing must add at least this much: order slots and attention are scarce
MIN_EXTRA_FRAC = 0.02        # ignore gains under 2% of the sell-now value
DOCK_MIN = 2.0               # minutes to dock and sell somewhere on the way
FALLBACK_RATE = 1_000_000.0  # ISK/hr when the planner finds nothing else to do


def _minutes(p, jumps):
    return jumps * p.jump_seconds / 60.0


def sell_plan(con, g, p, dest=None, world=None, min_value=100_000.0, rate=None):
    """world: optional {type_id: rows from bestprice.best_prices} for the stacks you checked worldwide.
    -> dict(rate, path, rows=[...], summary=...)"""
    cur = g.id_of(p.current_system)
    top = plan(con, dataclasses.replace(p, consider_ship_swaps=False), 10, False)
    rate = rate or (max(top[0].isk_per_hour, FALLBACK_RATE) if top else FALLBACK_RATE)
    if dest:
        path = g.route(cur, g.id_of(dest), 60, p.avoid_yellow).path
    elif top and top[0].waypoints:
        path = [cur] + list(top[0].waypoints)
    else:
        path = [cur]
    on_path = set(path[1:])
    reach = g.reach(cur, max(p.max_jumps * 3, 6), p.avoid_yellow)
    sells, buys = load_books(con, set(reach) | set(path))
    dock = _bids_at(con, p.current_location_id) if p.current_location_id else None
    vol = {r[0]: r[1] for r in con.execute("SELECT type_id,volume FROM types")}
    name = {r[0]: r[1] for r in con.execute("SELECT type_id,name FROM types")}
    world = world or {}
    rows = []
    for r in con.execute("SELECT type_id,quantity FROM inventory WHERE system_id=?", (cur,)).fetchall():
        tid, qty = r["type_id"], r["quantity"]
        local_bids = dock.get(tid, []) if dock is not None else buys.get(tid, {}).get(cur, [])
        sold0, now = sell_into_bids(local_bids, qty, p.sales_tax)
        asks = sells.get(tid, {}).get(cur, [])
        list_net = qty * asks[0][0] * (1 - p.broker_fee - p.sales_tax) if asks else 0.0
        opts = [("SELL NOW here", now, 0.0, "")]
        if list_net > now * 1.15 and list_net > 0:
            opts.append(("LIST here (waits)", list_net, 0.0, "needs an order slot; sells over days"))
        for s, rt in reach.items():                        # every system we can reach: on the trip, or a detour
            if s == cur:
                continue
            sold, net = sell_into_bids(buys.get(tid, {}).get(s, []), qty, p.sales_tax)
            if not sold:
                continue
            if s in on_path:
                opts.append((f"CARRY along the trip, sell at {g.name[s]}", net, DOCK_MIN, f"{rt.jumps} jumps, on your way"))
            else:
                opts.append((f"DETOUR to {g.name[s]}", net, 2 * _minutes(p, rt.jumps) + 2 * DOCK_MIN, f"{rt.jumps} jumps each way"))
        for d in world.get(tid, [])[:5]:
            if d["jumps"] is None or d["system"] == g.name[cur]:
                continue
            opts.append((f"HAUL to {d['system']} (best market)", d["net"], 2 * _minutes(p, d["jumps"]) + 2 * DOCK_MIN,
                         f"{d['jumps']} jumps each way" + (f", GANKS x{d['gank']}" if d["gank"] else "")))
        scored = []
        for label, net, mins, note in opts:
            extra = net - now
            gain = extra - rate * mins / 60.0
            ok = label.startswith("SELL NOW") or (extra >= MIN_EXTRA_FRAC * max(now, 1.0) and gain > 0)
            scored.append((gain if not label.startswith("SELL NOW") else 0.0, label, net, mins, note, ok, extra))
        scored = [s for s in scored if s[5]]
        scored.sort(key=lambda x: -x[0])
        best = scored[0]
        m3 = qty * (vol.get(tid, 0) or 0.0001)
        rows.append({"name": name.get(tid, tid), "qty": qty, "now": now, "m3": m3, "best_label": best[1], "best_net": best[2],
                     "mins": best[3], "extra": best[6], "gain": best[0], "note": best[4], "sold_locally": sold0,
                     "list_gain": list_net - now})
    slots = order_slots(con)                                  # None = skills not synced: no limit applied
    listers = sorted([x for x in rows if x["best_label"].startswith("LIST")], key=lambda x: -x["list_gain"])
    for k, x in enumerate(listers):
        if x["list_gain"] < MIN_LIST_GAIN or (slots is not None and k >= slots):
            x["best_label"], x["best_net"], x["extra"], x["gain"] = "SELL NOW here", x["now"], 0.0, 0.0
            x["note"] = "listing gain too small" if x["list_gain"] < MIN_LIST_GAIN else "no free order slot"
    # hold check: carried stacks must fit; densest value per m3 first, the rest sell now
    carry = sorted([x for x in rows if not x["best_label"].startswith(("SELL", "LIST"))], key=lambda x: -(x["best_net"] / max(x["m3"], 1e-6)))
    room = p.cargo_m3
    for x in carry:
        if x["m3"] <= room:
            room -= x["m3"]
        else:
            x["best_label"], x["best_net"], x["mins"], x["extra"], x["gain"] = "SELL NOW here (hold full)", x["now"], 0.0, 0.0, 0.0
    rows = [x for x in rows if max(x["now"], x["best_net"]) >= min_value]
    rows.sort(key=lambda x: -max(x["now"], x["best_net"]))
    return {"rate": rate, "path": [g.name[s] for s in path], "rows": rows, "carry_m3": p.cargo_m3 - room}


def format_sellplan(res, limit=14):
    L = [f"Your time is worth about {res['rate']:,.0f} ISK/hr (your best alternative task), so an option must earn more than that "
         f"for the extra minutes it costs.", f"Trip you are making: {' > '.join(res['path'])}" if len(res["path"]) > 1 else
         "No trip planned: carrying only counts as a detour.", ""]
    L.append(f"{'item':<30} {'qty':>9} {'sell now':>13}  verdict")
    for x in res["rows"][:limit]:
        if x["best_label"].startswith(("SELL", "LIST")) or x["extra"] <= 0:
            L.append(f"{x['name'][:30]:<30} {x['qty']:>9,} {x['now']:>13,.0f}  {x['best_label']}"
                     + (f"  ({x['note']})" if x["note"] else ""))
        else:
            L.append(f"{x['name'][:30]:<30} {x['qty']:>9,} {x['now']:>13,.0f}  {x['best_label']}: {x['best_net']:,.0f} "
                     f"(+{x['extra']:,.0f}, {x['mins']:.0f} min; {x['note']})")
    now_total = sum(x["now"] for x in res["rows"] if x["best_label"].startswith("SELL"))
    L += ["", f"Sell-now stacks total {now_total:,.0f} ISK. Carry space used: {res['carry_m3']:,.0f} m3."]
    return "\n".join(L)
