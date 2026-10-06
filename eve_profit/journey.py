"""`journey --to Jita`: one trip, planned as a whole. Pick up the stock you own on or near the route, buy goods that
sell for more further along (or at the end), sell what pays on the way, and close out the rest at the destination area.
Everything stays on the safe route (never red; yellow penalised); small detours are priced as time."""
from .basis import cost_basis, stack_basis
from .orders import load_books, sell_into_bids, walk_trade

DOCK_MIN = 2.0          # minutes per station you stop at
DEST_RADIUS = 4         # "close out" can use any market this many jumps around the destination
MIN_TRADE_PROFIT = 50_000.0
MAX_TRADES = 12
TIME_VALUE_ISK_HR = 6_000_000.0   # what an hour of your time is worth when deciding if a side trip is worth it


def _geometry(g, p, dest_name, detour):
    cur, dest = g.id_of(p.current_system), g.id_of(dest_name)
    route = g.route(cur, dest, 80, p.avoid_yellow)
    if route is None:
        raise ValueError(f"no safe route from {p.current_system} to {dest_name}")
    path = route.path
    near = {}                                   # system -> (position along the route, one-way detour jumps)
    for i, s in enumerate(path):
        for t, r in g.reach(s, detour, p.avoid_yellow).items():
            if t not in near or r.jumps < near[t][1]:
                near[t] = (i, r.jumps)
    end = len(path) - 1
    for t, r in g.reach(dest, DEST_RADIUS, p.avoid_yellow).items():      # close-out markets around the destination
        if t not in near or r.jumps < near[t][1]:
            near[t] = (end, r.jumps)
    return route, near


def journey_regions(g, p, dest_name, detour=2):
    _, near = _geometry(g, p, dest_name, detour)
    return sorted({g.region[s] for s in near})


def _ok(pos, a, b):
    """May goods bought at a be sold at b? Only later along the trip, or in a different system at the same point."""
    return a != b and pos[a] < pos[b]            # (position on the route, side-trip length): the order you visit them


def plan_journey(con, g, p, dest_name, detour=2, rate=TIME_VALUE_ISK_HR):
    route, near = _geometry(g, p, dest_name, detour)
    path, pos = route.path, near
    sells, buys = load_books(con, set(near))
    vol = {r[0]: (r[1] or 0.0001) for r in con.execute("SELECT type_id,volume FROM types")}
    name = {r[0]: r[1] for r in con.execute("SELECT type_id,name FROM types")}
    basis = cost_basis(con)
    room, wallet = p.cargo_m3, p.wallet_isk
    stops = {}                                   # system -> {"pick": [], "buy": [], "sell": []}

    def stop(s):
        return stops.setdefault(s, {"pick": [], "buy": [], "sell": []})

    stop(path[0]), stop(path[-1])               # you start and finish there anyway
    per_min = rate / 60.0

    def tcost(s):
        """ISK value of the time a new stop costs: the side trip there and back plus docking."""
        if s in stops:
            return 0.0
        return (2 * pos[s][1] * p.jump_seconds / 60.0 + DOCK_MIN) * per_min

    stock_net = 0.0
    held, carried, in_place = [], [], []
    ids = ",".join(str(int(s)) for s in near) or "0"
    for r in con.execute(f"SELECT type_id,system_id,quantity FROM inventory WHERE system_id IN ({ids})").fetchall():
        tid, a, qty = r["type_id"], r["system_id"], r["quantity"]
        best = None
        for b, bids in buys.get(tid, {}).items():
            if not (b == a or _ok(pos, a, b)):
                continue
            sold, net = sell_into_bids(bids, qty, p.sales_tax)
            if sold and (best is None or net - tcost(b) > best[0] - tcost(best[2])):
                best = (net, sold, b)
        if not best or best[0] - tcost(best[2]) - (tcost(a) if a != best[2] else 0.0) <= 0:
            continue
        cost, covered = stack_basis(basis, tid, qty)
        if covered and best[0] < cost / covered * min(best[1], covered):
            held.append({"name": name.get(tid, tid), "qty": qty, "cost": cost, "best": best[0], "at": g.name[best[2]]})
            continue
        item = {"tid": tid, "name": name.get(tid, tid), "from": a, "at": best[2], "sold": best[1], "net": best[0],
                "m3": best[1] * vol.get(tid, 0.0001)}
        (in_place if best[2] == a else carried).append(item)
    for d in sorted(in_place, key=lambda d: -d["net"]):   # sold where it already lies: no hold space needed
        if d["net"] <= tcost(d["from"]):
            continue
        stop(d["from"])["sell"].append((d["name"], d["sold"], d["net"]))
        stock_net += d["net"]
    carried.sort(key=lambda d: -(d["net"] / max(d["m3"], 1e-6)))
    left_behind = []
    for d in carried:
        units = min(d["sold"], int(room / (d["m3"] / d["sold"]) + 1e-9))
        if units <= 0:
            left_behind.append(d)
            continue
        f = units / d["sold"]
        if d["net"] * f <= tcost(d["from"]) + tcost(d["at"]):
            continue
        room -= d["m3"] * f
        stop(d["from"])["pick"].append((d["name"], units, 0.0))
        stop(d["at"])["sell"].append((d["name"], units, d["net"] * f))
        stock_net += d["net"] * f

    cands = []                                    # trades: buy at a (asks), sell at b (bids) further along
    for tid, asks_by in sells.items():
        bids_by = buys.get(tid)
        if not bids_by:
            continue
        top_bid = max(b[0][0] for b in bids_by.values())
        for a, asks in asks_by.items():
            if asks[0][0] >= top_bid * (1 - p.sales_tax):
                continue
            for b, bids in bids_by.items():
                if not _ok(pos, a, b) or bids[0][0] * (1 - p.sales_tax) <= asks[0][0]:
                    continue
                units, cost, rev = walk_trade(asks, bids, max(1, int(max(room, 1) / vol.get(tid, 0.0001))), wallet, p.sales_tax)
                if units and rev - cost > MIN_TRADE_PROFIT:
                    cands.append(((rev - cost) / (units * vol.get(tid, 0.0001)), tid, a, b))
    cands.sort(reverse=True)
    trade_profit, used_pairs, n = 0.0, set(), 0
    for _, tid, a, b in cands:
        if n >= MAX_TRADES or room <= 0 or wallet <= 0:
            break
        if (tid, a) in used_pairs:
            continue
        v = vol.get(tid, 0.0001)
        units, cost, rev = walk_trade(sells[tid][a], buys[tid][b], int(room / v + 1e-9), wallet, p.sales_tax)
        if not units or rev - cost < MIN_TRADE_PROFIT + tcost(a) + tcost(b):
            continue
        used_pairs.add((tid, a))
        room -= units * v
        wallet -= cost
        trade_profit += rev - cost
        n += 1
        stop(a)["buy"].append((name.get(tid, tid), units, cost))
        stop(b)["sell"].append((name.get(tid, tid), units, rev))

    jumps = route.jumps + sum(2 * pos[s][1] for s in stops if s in pos)
    visited = set(stops)
    hours = jumps * p.jump_seconds / 3600.0 + len(visited) * DOCK_MIN / 60.0
    total = stock_net + trade_profit
    order = sorted(stops, key=lambda s: (pos[s][0], pos[s][1]))
    return {"route": [g.name[s] for s in path], "jumps": route.jumps, "extra_jumps": jumps - route.jumps,
            "stops": [(g.name[s], pos[s][1], stops[s]) for s in order], "stock_net": stock_net, "trade_profit": trade_profit,
            "total": total, "hours": hours, "isk_hr": total / hours if hours else 0.0, "used_m3": p.cargo_m3 - room,
            "cargo_m3": p.cargo_m3, "held": held, "left_behind": left_behind, "dest": dest_name, "path_ids": path}


def format_journey(res, limit=8):
    L = [f"JOURNEY to {res['dest']}: {res['jumps']} jumps on the safe route"
         + (f" + {res['extra_jumps']} jumps of side trips" if res["extra_jumps"] else ""),
         "   " + " > ".join(res["route"]), ""]
    for sysname, detour, acts in res["stops"]:
        if not (acts["pick"] or acts["buy"] or acts["sell"]):
            continue
        L.append(f"AT {sysname}" + (f"  ({detour} jump{'s' if detour != 1 else ''} off the route, each way)" if detour else ""))
        for label, key in (("pick up", "pick"), ("buy", "buy"), ("sell", "sell")):
            rows = sorted(acts[key], key=lambda x: -x[2])
            for nm, q, isk in rows[:limit]:
                L.append(f"   {label:<8} {q:>9,} x {nm:<34}" + (f" {isk:>14,.0f} ISK" if isk else ""))
            if len(rows) > limit:
                L.append(f"   {label:<8} ...and {len(rows) - limit} more")
    L += ["", f"Stock sold along the way : {res['stock_net']:>14,.0f} ISK",
          f"Trade profit on the way  : {res['trade_profit']:>14,.0f} ISK",
          f"TOTAL                    : {res['total']:>14,.0f} ISK in about {res['hours'] * 60:,.0f} min "
          f"= {res['isk_hr']:,.0f} ISK/hr   (hold used {res['used_m3']:,.0f} of {res['cargo_m3']:,.0f} m3)"]
    if res["held"]:
        L += ["", "HELD BACK (would sell below what you paid on this trip):"]
        L += [f"   {d['qty']:>9,} x {d['name']:<32} paid {d['cost']:>12,.0f}, best here {d['best']:>12,.0f} at {d['at']}" for d in res["held"][:6]]
    if res["left_behind"]:
        L.append(f"\nLEFT BEHIND (hold full): {len(res['left_behind'])} stacks worth {sum(d['net'] for d in res['left_behind']):,.0f} ISK"
                 " - a second trip, or list them where they are")
    L += ["", "Compare with LISTING the same goods and waiting: that can pay more but may take weeks or never sell, and the "
          "ISK/hr above only counts your active time.",
          "Prices are from your last scan: refresh first with `journey --to NAME --live`, then confirm each buy with `check`."]
    return "\n".join(L)
