"""Hauling trades (buy at A, sell into buy orders at B) and inventory liquidation."""
from .opportunity import Opportunity
from .orders import load_books, sell_into_bids, walk_trade
from .risk import route_risk


def _names(g, path):
    return " > ".join(g.name[s] for s in path)


def _tail(g, path):
    return g.name[path[-1]]


def _dock_stops(con, tid, a, b, j1, j2):
    """Station/structure ids of the cheapest ask in A and best bid in B so autopilot docks there.
    -> [(waypoint_index, location_id)]; index -1 = before the first waypoint (already in A's system)."""
    ask = con.execute("SELECT location_id FROM orders WHERE type_id=? AND system_id=? AND is_buy=0 "
                      "ORDER BY price ASC LIMIT 1", (tid, a)).fetchone()
    bid = con.execute("SELECT location_id FROM orders WHERE type_id=? AND system_id=? AND is_buy=1 "
                      "ORDER BY price DESC LIMIT 1", (tid, b)).fetchone()
    stops = []
    if ask and ask[0]:
        stops.append((j1 - 1 if j1 > 0 else -1, ask[0]))
    if bid and bid[0]:
        stops.append((j1 + j2 - 1, bid[0]))
    return stops


def find_trades(con, g, p):
    cur = g.id_of(p.current_system)
    reach_a = g.reach(cur, p.pickup, p.avoid_yellow)
    reach_b = {a: g.reach(a, p.max_jumps, p.avoid_yellow) for a in reach_a}
    systems = set(reach_a)
    for r in reach_b.values():
        systems |= set(r)
    sells, buys = load_books(con, systems)
    vol = {r[0]: r[1] for r in con.execute("SELECT type_id,volume FROM types")}
    tname = {r[0]: r[1] for r in con.execute("SELECT type_id,name FROM types")}
    out = []
    for tid, by_sys in sells.items():
        if tid not in buys or vol.get(tid, 0) <= 0:
            continue
        cap_units = int(p.cargo_m3 // vol[tid])
        if cap_units < 1:
            continue
        for a, asks in by_sys.items():
            if a not in reach_a:
                continue
            for b, bids in buys[tid].items():
                if b == a or b not in reach_b[a]:
                    continue
                if bids[0][0] * (1 - p.sales_tax) <= asks[0][0]:
                    continue
                units, cost, rev = walk_trade(asks, bids, cap_units, p.wallet_isk, p.sales_tax)
                profit = rev - cost
                if units == 0 or profit < p.min_profit_isk or profit / cost < p.min_margin:
                    continue
                r1, r2 = reach_a[a], reach_b[a][b]
                l1, w1 = route_risk(g, r1.path, p.ship_value_isk)
                l2, w2 = route_risk(g, r2.path, p.ship_value_isk + cost)
                jumps = r1.jumps + r2.jumps
                secs = (jumps * p.jump_seconds + 2 * p.dock_overhead_s
                        + p.trade_overhead_s + w1 + w2)
                stops = _dock_stops(con, tid, a, b, r1.jumps, r2.jumps)
                out.append(Opportunity(
                    "trade",
                    f"Buy {units:,} x {tname.get(tid, tid)} @ {g.name[a]}, "
                    f"sell @ {g.name[b]}",
                    profit, l1 + l2, jumps, secs / 3600,
                    _names(g, r1.path) + " | " + _names(g, r2.path),
                    {"type_id": tid, "units": units, "cost": cost, "m3": units * vol[tid], "stops": stops, "from_sys": a, "to_sys": b},
                    waypoints=r1.path[1:] + r2.path[1:]))
    return out


def find_liquidations(con, g, p):
    """Best place to dump items you already own vs. selling in place. The trip starts where your
    ship IS: it includes getting to the stock, and never carries more than the hold fits."""
    out = []
    cur = g.id_of(p.current_system)
    from_cur = g.reach(cur, p.pickup * 2, p.avoid_yellow)
    tname = {r[0]: r[1] for r in con.execute("SELECT type_id,name FROM types")}
    vol = {r[0]: r[1] for r in con.execute("SELECT type_id,volume FROM types")}
    ctx = {}                                   # per stock system: (reach, buy books) computed once, not once per stack
    for inv in con.execute("SELECT type_id,system_id,quantity FROM inventory").fetchall():
        tid, sid, qty = inv["type_id"], inv["system_id"], inv["quantity"]
        r0 = from_cur.get(sid)
        if r0 is None:
            continue                      # stock is too far / only reachable through red space
        if vol.get(tid, 0) > 0:
            qty = min(qty, int(p.cargo_m3 // vol[tid]))      # one hold-load at a time
        if qty < 1:
            continue
        if sid not in ctx:
            reach_s = g.reach(sid, p.max_jumps, p.avoid_yellow)
            ctx[sid] = (reach_s, load_books(con, reach_s)[1])
        reach, buys = ctx[sid]
        _, local = sell_into_bids(buys[tid].get(sid, []), qty, p.sales_tax)
        best = None
        for b, bids in buys[tid].items():
            if b == sid:
                continue
            sold, net = sell_into_bids(bids, qty, p.sales_tax)
            if best is None or net > best[2]:
                best = (b, sold, net)
        if not best:
            continue
        b, sold, net = best
        uplift = net - local
        if uplift < p.min_profit_isk:
            continue
        rt = reach[b]
        l0, w0 = route_risk(g, r0.path, p.ship_value_isk)
        l1, w1 = route_risk(g, rt.path, p.ship_value_isk + net)
        jumps = r0.jumps + rt.jumps
        secs = jumps * p.jump_seconds + 2 * p.dock_overhead_s + p.trade_overhead_s + w0 + w1
        out.append(Opportunity(
            "liquidate",
            f"Collect + sell {sold:,} x {tname.get(tid, tid)} (stock at {g.name[sid]}) at {g.name[b]} "
            f"(vs {local:,.0f} ISK selling at {g.name[sid]})",
            uplift, l0 + l1, jumps, secs / 3600, _names(g, r0.path) + " | " + _names(g, rt.path),
            {"type_id": tid, "units": sold, "net": net, "local_net": local, "from_sys": sid},
            waypoints=r0.path[1:] + rt.path[1:]))
    return out
