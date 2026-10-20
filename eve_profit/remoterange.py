"""BUY ORDERS WITH A RANGE: a buy order's range ("40 jumps", "region", "solar system", "station") says how far away a seller may be and still sell into it. If you are docked
within range AND in the SAME REGION, you can sell to that order from where you stand (the Sell window lists it with its own station): no travel. The EVE market is
per REGION: an order in another region never shows in your Sell window, whatever its range (seen in game: a 40-jump order in Amarr, Domain, was not offered in Jita, The Forge).
Ranges are stored at scan time (order_range); `remote_bid` finds the best one that reaches you."""

STRING_RANGES = {"station": -2, "solarsystem": -1, "region": 10 ** 6}


def _num(r):
    r = str(r).lower()
    if r in STRING_RANGES:
        return STRING_RANGES[r]
    try:
        return int(r)
    except ValueError:
        return -2


def store(con, rows):
    """rows = ESI order dicts (with 'order_id' and 'range'): keep each buy order's range."""
    con.execute("CREATE TABLE IF NOT EXISTS order_range(order_id INTEGER PRIMARY KEY, rng TEXT)")
    con.executemany("INSERT OR REPLACE INTO order_range VALUES(?,?)", [(o["order_id"], str(o["range"])) for o in rows if o.get("is_buy_order") and o.get("range") is not None])


def gate_jumps(g, src, limit=40):
    """{system: gate jumps from src} ignoring security (a range counts gates, not safe routes)."""
    dist, frontier = {src: 0}, [src]
    for d in range(1, limit + 1):
        nxt = []
        for u in frontier:
            for v in g.adj.get(u, ()):
                if v not in dist:
                    dist[v] = d
                    nxt.append(v)
        frontier = nxt
        if not frontier:
            break
    return dist


def remote_bid(con, g, tid, qty, from_sid, from_loc, tax, min_sec=0.5):
    """-> {net, price, system, station, rng, jumps, sold} for the best buy order OUTSIDE your station whose range reaches you (high-sec buyers only), or None."""
    try:
        rows = con.execute("SELECT o.order_id,o.price,o.volume_remain,o.min_volume,o.system_id,o.region_id,o.location_id,r.rng FROM orders o JOIN order_range r ON r.order_id=o.order_id "
                           "WHERE o.type_id=? AND o.is_buy=1 AND o.volume_remain>0 ORDER BY o.price DESC", (tid,)).fetchall()
    except Exception:                                                   # noqa: BLE001
        return None
    if not rows:
        return None
    reach = gate_jumps(g, from_sid)
    try:
        my_region = g.region[from_sid]
    except Exception:                                                   # noqa: BLE001
        my_region = None
    best, left, net = None, qty, 0.0
    for r in rows:
        sid, rng = r["system_id"], _num(r["rng"])
        if g.sec.get(sid, 0.0) < min_sec or r["location_id"] == from_loc:
            continue
        j = reach.get(sid)
        if r["region_id"] != my_region:
            continue                                                    # another region's market: not offered to you, whatever the range
        ok = rng == 10 ** 6 or (rng >= 0 and j is not None and j <= rng) or (rng == -1 and sid == from_sid)
        if not ok or r["volume_remain"] < max(r["min_volume"], 1):
            continue
        take = min(left, r["volume_remain"])
        net += take * r["price"] * (1 - tax)
        if best is None:
            best = {"price": r["price"], "system": g.name[sid], "station": r["location_id"], "rng": r["rng"], "jumps": j if j is not None else 0}
        left -= take
        if left <= 0:
            break
    if best is None or left == qty:
        return None
    best.update({"net": net, "sold": qty - left})
    return best


MAX_ORDERS = 60          # best-priced buy orders per item looked at


def entry_options(con, g, p, tid, qty, cur, reach, now_net):
    """Buy orders elsewhere (high-sec, a scanned region) that pay clearly more than `now_net`, and the NEAREST place you can sell to them: any station system in the ORDER'S region
    within the order's range of it (you do not have to go to the order's own station). -> [(net, entry system name, jumps from you, order system, price, rng)] best first.
    `reach` = g.reach(cur, ...) (safe routes from you)."""
    try:
        rows = con.execute("SELECT o.price,o.volume_remain,o.min_volume,o.system_id,o.region_id,r.rng FROM orders o JOIN order_range r ON r.order_id=o.order_id "
                           "WHERE o.type_id=? AND o.is_buy=1 AND o.volume_remain>=? ORDER BY o.price DESC LIMIT ?", (tid, 1, MAX_ORDERS * 3)).fetchall()
        stations = {r[0] for r in con.execute("SELECT DISTINCT system_id FROM stations")}
    except Exception:                                                   # noqa: BLE001
        return []
    out, tax = [], p.sales_tax
    for r in rows:
        if len(out) >= MAX_ORDERS:
            break
        osys, rng = r["system_id"], _num(r["rng"])
        if g.sec.get(osys, 0.0) < 0.5 or r["volume_remain"] < max(r["min_volume"], qty if r["min_volume"] > 1 else 1):
            continue
        sold = min(qty, r["volume_remain"])
        net = sold * r["price"] * (1 - tax)
        if net <= now_net * 1.1 + 5_000:
            continue
        if rng == -2:                                                   # station range: only that station
            cand = [osys]
        elif rng == -1:
            cand = [osys]
        else:
            lim = 40 if rng == 10 ** 6 else rng
            cand = list(gate_jumps(g, osys, min(lim, 40)))
        best = None
        for s in cand:
            if s in stations and s in reach and g.sec.get(s, 0.0) >= 0.5 and g.region.get(s) == g.region.get(osys):
                j = reach[s].jumps
                if best is None or j < best[0]:
                    best = (j, s)
        if best is None:
            continue
        out.append((net, g.name[best[1]], best[0], g.name[osys], r["price"], r["rng"]))
    out.sort(key=lambda x: (-x[0], x[2]))
    return out[:5]
