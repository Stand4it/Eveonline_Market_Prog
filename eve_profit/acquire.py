"""How to get an item a mission or goal asks for, at the lowest REAL cost: buy it (cheapest safe station you can reach, counting the detour at the
value of your time) or build it from a blueprint (materials at their cheapest reachable asks, minus what you already hold). The answer is a plan; `next`
shows only its FIRST action, `next --plan` shows the comparison. A purchase you made is remembered for 2 hours (ESI assets lag about an hour)."""
import json
import time

SANITY_X = 2.5                     # a source dearer than 2.5x the cheapest known ask is dropped while a saner one exists
JUMP_VALUE_ISK = 50_000.0            # 3 minutes per jump at 1,000,000 ISK/hr: a detour has to save more than this per jump
SAFE_SEC = 0.5
KEY = "acquired"
MAX_AGE_S = 2 * 3600


def _one(con, sql, args=()):
    try:
        return con.execute(sql, args).fetchone()
    except Exception:                                                   # noqa: BLE001
        return None


def station_name(con, loc_id):
    r = _one(con, "SELECT name FROM stations WHERE station_id=?", (loc_id,))
    if r and r[0]:
        return r[0]
    r = _one(con, "SELECT name FROM structures WHERE structure_id=?", (loc_id,))
    return r[0] if r and r[0] else ""


def sources(con, g, p, item, qty=1, dest=None, max_jumps=14, limit=12):
    """Cheapest places to BUY `item`, best first: [{system, loc, station, price, jumps, detour, cost}] (safe systems, reachable, enough volume).
    cost = price x qty + detour jumps x JUMP_VALUE_ISK (detour = extra jumps compared with flying straight to `dest`; without dest, all jumps)."""
    try:
        cur = g.id_of(p.current_system)
        reach = g.reach(cur, max_jumps, p.avoid_yellow)
    except Exception:                                                   # noqa: BLE001
        return []
    try:
        rows = con.execute("SELECT o.system_id,o.location_id,MIN(o.price),SUM(o.volume_remain) FROM orders o JOIN types t ON t.type_id=o.type_id "
                           "WHERE t.name=? COLLATE NOCASE AND o.is_buy=0 GROUP BY o.system_id,o.location_id", (item,)).fetchall()
    except Exception:                                                   # noqa: BLE001
        return []
    cand = [(r[0], r[1], float(r[2]), r[3]) for r in rows if r[0] in reach and (r[3] or 0) >= qty and g.sec[r[0]] >= SAFE_SEC]
    try:                                                                # price sanity: a quote far above the cheapest ask anywhere is a stray/stale order, not "the cheapest place"
        floor = _one(con, "SELECT MIN(o.price) FROM orders o JOIN types t ON t.type_id=o.type_id WHERE t.name=? COLLATE NOCASE AND o.is_buy=0", (item,))
        floor = float(floor[0]) if floor and floor[0] else 0.0
    except Exception:                                                   # noqa: BLE001
        floor = 0.0
    sane = [r for r in cand if r[2] <= floor * SANITY_X] if floor > 0 else cand
    if sane and len(sane) < len(cand):                                  # drop a dear quote only when it is not cheaper ONCE THE TRIP IS COUNTED: a 9,996 Miner I
        cheapest = min(sane, key=lambda r: r[2] * qty + reach[r[0]].jumps * JUMP_VALUE_ISK)          # 2 jumps away beats a 2,211 one 13 jumps away
        bar = cheapest[2] * qty + reach[cheapest[0]].jumps * JUMP_VALUE_ISK
        cand = [r for r in cand if r[2] <= floor * SANITY_X or r[2] * qty + reach[r[0]].jumps * JUMP_VALUE_ISK < bar]
    cand.sort(key=lambda r: r[2] + reach[r[0]].jumps * JUMP_VALUE_ISK)    # a near listing a little dearer beats a far bargain: rank by price + the trip BEFORE cutting to `limit`
    did = None
    direct = 0
    if dest:
        try:
            did = g.id_of(dest)
            direct = reach[did].jumps if did in reach else (g.route(cur, did, 60, p.avoid_yellow).jumps)
        except Exception:                                               # noqa: BLE001
            did = None
    out = []
    for sid, loc, price, vol in cand[:limit]:
        jumps = reach[sid].jumps
        if did is not None:
            try:
                tail = g.route(sid, did, 60, p.avoid_yellow).jumps
            except Exception:                                           # noqa: BLE001
                continue
            detour = max(0, jumps + tail - direct)
        else:
            detour = jumps
        out.append({"system": g.name[sid], "sid": sid, "loc": loc, "station": station_name(con, loc), "price": price, "jumps": jumps,
                    "detour": detour, "cost": price * qty + detour * JUMP_VALUE_ISK})
    out.sort(key=lambda r: r["cost"])
    return out


def held(con, item):
    """Units of `item` you hold (hangars + ship cargo as synced) or bought in the last 2 hours (not in ESI yet)."""
    r = _one(con, "SELECT COALESCE(SUM(i.quantity),0) FROM inventory i JOIN types t ON t.type_id=i.type_id WHERE t.name=? COLLATE NOCASE", (item,))
    n = int(r[0] or 0) if r else 0
    try:
        m = _one(con, "SELECT value FROM meta WHERE key=?", (KEY,))
        st = json.loads(m[0]) if m else {}
        for it, v in st.items():
            if it.lower() == item.lower() and time.time() - v["t"] <= MAX_AGE_S:
                n = max(n, int(v["qty"]))
    except Exception:                                                   # noqa: BLE001
        pass
    try:                                                                # bought in the last 2 h per the wallet (it syncs within minutes; the hangar list lags an hour)
        since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - MAX_AGE_S))
        r = _one(con, "SELECT COALESCE(SUM(x.quantity),0) FROM transactions x JOIN types t ON t.type_id=x.type_id WHERE t.name=? COLLATE NOCASE "
                      "AND x.is_buy=1 AND x.date>=?", (item, since))
        n = max(n, int(r[0] or 0) if r else 0)
    except Exception:                                                   # noqa: BLE001
        pass
    return n


def confirm(con, item, qty):
    """`stop` on the buy step: remember the purchase until ESI shows it. -> text."""
    try:                                                                # purchases ADD up (5 then 1 = 6); one name per item whatever its spelling;
        m = _one(con, "SELECT value FROM meta WHERE key=?", (KEY,))     # the same purchase confirmed twice (done, then stop) counts once
        st = json.loads(m[0]) if m else {}
        r = _one(con, "SELECT name FROM types WHERE name=? COLLATE NOCASE", (item,))
        item = r[0] if r else item
        old_k = next((k for k in st if k.lower() == item.lower()), None)
        old = st.pop(old_k) if old_k else None
        now = time.time()
        if old and now - old["t"] <= MAX_AGE_S:
            if old.get("last") == int(qty) and now - old.get("last_t", 0) < 10 * 60:
                st[item] = old                                          # a repeat of the last confirmation: not a new purchase
                con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (KEY, json.dumps(st)))
                con.commit()
                return f"Noted (already counted): {old['qty']:,} x {item} bought in total."
            total = int(old["qty"]) + int(qty)
        else:
            total = int(qty)
        st[item] = {"qty": total, "t": now, "last": int(qty), "last_t": now}
        con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (KEY, json.dumps(st)))
        con.commit()
    except Exception:                                                   # noqa: BLE001
        return ""
    return f"Noted: {qty:,} x {item} bought ({total:,} in total; ESI shows it in your hangar within about an hour)."


def build_cost(con, g, p, item, dest=None):
    """Cost of BUILDING `item` from its blueprint (SDE recipe, no material efficiency): -> {cost, lines, steps} or None.
    Materials you hold are subtracted; each missing one is priced at its cheapest safe reachable ask (mining/refining them yourself is not priced)."""
    bp = _one(con, "SELECT type_id FROM types WHERE name=? COLLATE NOCASE", (item + " Blueprint",))
    if not bp:
        return None
    try:
        mats = con.execute("SELECT m.material_id,m.quantity,t.name FROM bp_materials m JOIN types t ON t.type_id=m.material_id WHERE m.blueprint_id=?", (bp[0],)).fetchall()
    except Exception:                                                   # noqa: BLE001
        return None
    if not mats:
        return None
    total, lines, steps = 0.0, [], []
    for mid, q, name in mats:
        need = max(0, q - held(con, name))
        if not need:
            lines.append(f"{q:,} x {name}: in your hangar")
            continue
        src = sources(con, g, p, name, need, dest, limit=4)
        if not src:
            return None
        s = src[0]
        total += s["price"] * need
        lines.append(f"{need:,} x {name}: ~{s['price'] * need:,.0f} at {s['system']}")
        steps.append({"item": name, "qty": need, **s})
    return {"cost": total, "lines": lines, "steps": steps}


def live_refresh(con, g, p, item, qty=1, dest=None):
    """Fresh public orders for this ONE item in the regions of its best sources (a few calls): so the trip is planned on today's prices, not on the last
    scan, and you do not arrive to find it is no longer the best price. -> True when refreshed."""
    import os
    if os.environ.get("EVE_NO_LIVE"):
        return False
    try:
        from .esi import ESI, refresh_item
        tid = _one(con, "SELECT type_id FROM types WHERE name=? COLLATE NOCASE", (item,))
        if not tid:
            return False
        src = sources(con, g, p, item, qty, dest, limit=6)
        regs = sorted({g.region[x["sid"]] for x in src[:4]} | {g.region[g.id_of(p.current_system)]})
        refresh_item(con, ESI(timeout=12), regs, tid[0])
        return True
    except Exception:                                                   # noqa: BLE001
        return False


def best_way(con, g, p, item, qty=1, dest=None, can_build=True, live=False):
    """Compare BUY (cheapest reachable source incl. detour) with BUILD. -> dict(mode, cost, src, buy, build, lines) or None when nothing is known.
    live=True first re-reads this item's orders from ESI (use it for the step you are about to act on)."""
    fresh = live_refresh(con, g, p, item, qty, dest) if live and held(con, item) < qty else False
    n_held = held(con, item)
    if n_held >= qty:
        return {"mode": "held", "cost": 0.0, "item": item, "qty": qty, "lines": [f"{item}: you already hold {n_held:,}"], "buy": None, "build": None, "src": None}
    need = qty - n_held
    src = sources(con, g, p, item, need, dest)
    buy = src[0] if src else None
    build = build_cost(con, g, p, item, dest) if can_build else None
    if buy is None and build is None:
        return None
    lines = [] if not fresh else ["prices re-checked live just now"]
    if buy:
        alt = ""
        lines.append(f"BUY: {buy['price'] * need:,.0f} ISK at {buy['station'] or buy['system']} ({buy['jumps']} jumps from here"
                     + (f", {buy['detour']} extra jumps against going straight" if dest else "") + f"){alt}")
    if build:
        lines.append(f"BUILD: about {build['cost']:,.0f} ISK of materials ({'; '.join(build['lines'][:4])}) plus the job time; mining/refining them yourself is not priced")
    mode = "buy" if buy and (not build or buy["cost"] <= build["cost"]) else "build"
    lines = [l for l in lines if not l.startswith("BUILD" if mode == "buy" else "BUY")]      # ONE option only: the best, no alternatives
    return {"mode": mode, "cost": (buy["cost"] if mode == "buy" else build["cost"]), "item": item, "qty": need, "src": buy, "buy": buy, "build": build, "lines": lines}


def first_action(con, g, p, way, hop_to):
    """The ONE next action toward getting the item, as step text (or '' when it is already held). hop_to(system) -> text of the next jump toward it."""
    if not way or way["mode"] == "held":
        return ""
    if way["mode"] == "buy":
        s = way["buy"]
        item, qty = way["item"], way["qty"]
        if s["system"] == p.current_system:
            head = f"STEP: ACQUIRE {qty:,} x {item} - BUY at {s['station'] or s['system']} (about {s['price'] * qty:,.0f} ISK)"
            try:
                from .tradestep import STATION
                STATION[head] = int(s["loc"])
            except Exception:                                           # noqa: BLE001
                pass
            return "\n".join([head, f"   DO ONLY THIS: dock at {s['station'] or s['system']}, Market > {item} > Buy > the cheapest sell order, {qty:,} unit(s). Check the live price first.",
                              f"   Bought it without the timer? Tell the tool:  python -m eve_profit done --goal \"bought {qty} {item}\"",
                              f"   LATER: {'; '.join(way['lines'])}"])
        return hop_to(s["system"], f"to buy {item} ({s['price'] * qty:,.0f} ISK at {s['station'] or s['system']}, the cheapest safe place counting the detour)", way["lines"])
    st = (way["build"] or {}).get("steps") or []
    if st:
        s = st[0]
        if s["system"] == p.current_system:
            head = f"STEP: ACQUIRE {s['qty']:,} x {s['item']} - BUY at {s['station'] or s['system']} (material for building {way['item']}, about {s['price'] * s['qty']:,.0f} ISK)"
            try:
                from .tradestep import STATION
                STATION[head] = int(s["loc"])
            except Exception:                                           # noqa: BLE001
                pass
            return "\n".join([head, f"   DO ONLY THIS: dock at {s['station'] or s['system']}, Market > {s['item']} > Buy > the cheapest sell orders, {s['qty']:,} units.",
                              f"   LATER: {'; '.join(way['lines'])}"])
        return hop_to(s["system"], f"to buy {s['item']} for building {way['item']}", way["lines"])
    return ""
