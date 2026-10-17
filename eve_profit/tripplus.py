"""Every step that sends you somewhere gets the same extras, so no trip is ever just a trip:
   * AGENTS on the route (accept a mission in passing: it also models the career),
   * things you NEED anyway (gear on the keep list, spare probes...) that are much cheaper on the route than here,
   * trades on the way there and back (spare hold space, half the profit counted).
`extras(con, g, p, dest)` -> {"lines": [...], "isk": N, "minutes": N}; lines are ready to print under a step."""
from .along import keep_rules


def _route(g, p, dest):
    try:
        r = g.route(g.id_of(p.current_system), g.id_of(dest), 60, p.avoid_yellow)
        return r.path if r else []
    except Exception:                                                   # noqa: BLE001
        return []


def _agents(g, path):
    try:
        from .journey import _agents_on_route
        names = [g.name[s] for s in path]
        return [f"agent on the route: {a['name']} ({a['type']}, {a['system']}): accept a mission in passing" for a in _agents_on_route(names)[:3]]
    except Exception:                                                   # noqa: BLE001
        return []


def cheap_needs_pairs(con, g, p, path, min_save=0.20, min_isk=3000.0):
    """Gear you keep but are short of (keep_items.json qty) that sells >=20% cheaper somewhere on the route than in your own system."""
    out = []
    here = g.id_of(p.current_system)
    ids = ",".join(str(int(s)) for s in set(path) | {here}) or "0"
    for key, rule in keep_rules(con).items():
        want = rule.get("qty")
        if not want:
            continue
        r = con.execute("SELECT type_id FROM types WHERE name=? COLLATE NOCASE", (rule["item"],)).fetchone()
        if not r:
            continue
        tid = r[0]
        have = con.execute("SELECT COALESCE(SUM(quantity),0) FROM inventory WHERE type_id=?", (tid,)).fetchone()[0]
        short = int(want) - int(have)
        if short <= 0:
            continue
        rows = con.execute(f"SELECT system_id, MIN(price) FROM orders WHERE type_id=? AND is_buy=0 AND system_id IN ({ids}) GROUP BY system_id", (tid,)).fetchall()
        prices = {s: pr for s, pr in rows}
        if not prices:
            continue
        s_best = min(prices, key=prices.get)
        local = prices.get(here)
        if s_best == here:
            continue
        save = ((local - prices[s_best]) * short) if local else 0.0
        if (local and prices[s_best] <= local * (1 - min_save) and save >= min_isk):
            out.append((f"need anyway: {short:,} x {rule['item']} is ~{prices[s_best]:,.0f} each at {g.name[s_best]} on the route (here {local:,.0f}): buy there, saves ~{save:,.0f} ISK", save))
    return out


def cheap_needs(con, g, p, path, **kw):
    return [l for l, _ in cheap_needs_pairs(con, g, p, path, **kw)]


def needs_saving(con, g, p, dest):
    """ISK saved by buying the gear you lack on the way to dest (counts in the ISK/hr ranking of that trip)."""
    path = _route(g, p, dest)
    try:
        return sum(s for _, s in cheap_needs_pairs(con, g, p, path)) if path else 0.0
    except Exception:                                                   # noqa: BLE001
        return 0.0


def extras(con, g, p, dest, m3=0.0):
    out = {"lines": [], "isk": 0.0, "minutes": 0.0}
    if g is None or p is None or not dest:
        return out
    path = _route(g, p, dest)
    if not path:
        return out
    out["lines"] += _agents(g, path)
    try:                                                                # stock lying in hangars along the route: collect it as you pass (consolidates your inventory)
        for d in pickups(con, g, p, path, m3):
            out["lines"].append(f"pick up in {d['system']}: {d['qty']:,} x {d['item']} ({d['m3']:,.0f} m3, ~{d['value']:,.0f} ISK): consolidates your stock, rides along")
    except Exception:                                                   # noqa: BLE001
        pass
    try:
        out["lines"] += cheap_needs(con, g, p, path)
    except Exception:                                                   # noqa: BLE001
        pass
    try:
        from .dailygoals import _trades
        isk, mins, lines = _trades(con, g, p, dest, m3)
        if isk > 0:
            out["isk"], out["minutes"] = isk, mins
            out["lines"] += lines + [f"trades there and back add ~{isk:,.0f} ISK (half counted) for ~{mins:.0f} more min"]
    except Exception:                                                   # noqa: BLE001
        pass
    return out


def cheap_needs_here(con, g, p, home_name, min_save=0.20, min_isk=3000.0):
    """Gear you keep but are short of (keep_items.json) that is >=20% cheaper in THIS system than at home: buy it now, you are here anyway."""
    out = []
    try:
        here, home = g.id_of(p.current_system), g.id_of(home_name)
    except Exception:                                                   # noqa: BLE001
        return out
    if here == home:
        return out
    for key, rule in keep_rules(con).items():
        want = rule.get("qty")
        if not want:
            continue
        r = con.execute("SELECT type_id FROM types WHERE name=? COLLATE NOCASE", (rule["item"],)).fetchone()
        if not r:
            continue
        tid = r[0]
        have = con.execute("SELECT COALESCE(SUM(quantity),0) FROM inventory WHERE type_id=?", (tid,)).fetchone()[0]
        short = int(want) - int(have)
        if short <= 0:
            continue
        ask = lambda sid: (con.execute("SELECT MIN(price) FROM orders WHERE type_id=? AND is_buy=0 AND system_id=?", (tid, sid)).fetchone() or [None])[0]
        a_here, a_home = ask(here), ask(home)
        if a_here and a_home and a_here <= a_home * (1 - min_save) and (a_home - a_here) * short >= min_isk:
            out.append(f"{short:,} x {rule['item']} ~{a_here:,.0f} each here (about {a_home:,.0f} at {home_name}): saves ~{(a_home - a_here) * short:,.0f} ISK")
    return out


PICKED_KEY = "picked"
PICKED_MAX_AGE_S = 2 * 3600


def _meta_json(con, key):
    import json
    try:
        r = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(r[0]) if r else {}
    except Exception:                                                   # noqa: BLE001
        return {}


def mark_picked(con, system_name):
    """`stop` on a PICK UP step: that system's stock is on board now (ESI shows the cargo within an hour): do not ask again for 2 h."""
    import json
    import time
    st = _meta_json(con, PICKED_KEY)
    st[system_name] = time.time()
    con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (PICKED_KEY, json.dumps(st)))
    con.commit()
    return f"Noted: the stock in {system_name} is picked up (it rides along and is sold or delivered where it pays most)."


def pickups(con, g, p, system_ids, mission_m3=0.0, limit=6):
    """Stock lying in hangars at `system_ids` (a trip's route) that fits the free cargo space, best value per m3 first: consolidates your stock as you travel.
    -> [{system, item, qty, m3, value}]. Gear on the keep list stays where it is; cargo you already carry is not counted."""
    import time
    try:
        from .along import keep_rules
        keep = keep_rules(con)
    except Exception:                                                   # noqa: BLE001
        keep = {}
    cargo = _meta_json(con, "cargo_now")
    picked = _meta_json(con, PICKED_KEY)
    cur = g.id_of(p.current_system)
    vol = {r[0]: (r[1] or 0.0) for r in con.execute("SELECT type_id,volume FROM types")}
    used = sum(int(q) * vol.get(int(t), 0.0) for t, q in cargo.items())
    room = max(0.0, float(p.cargo_m3) - used - float(mission_m3))
    try:
        adj = {r[0]: r[1] or 0.0 for r in con.execute("SELECT type_id,adjusted_price FROM prices")}
    except Exception:                                                   # noqa: BLE001
        adj = {}
    rows = []
    for sid in system_ids:
        name = g.name[sid]
        if time.time() - picked.get(name, 0) < PICKED_MAX_AGE_S:
            continue
        for r in con.execute("SELECT i.type_id,i.quantity,t.name FROM inventory i JOIN types t ON t.type_id=i.type_id WHERE i.system_id=?", (sid,)):
            tid, q, nm = r[0], r[1], r[2]
            if sid == cur:
                q -= int(cargo.get(str(tid), 0))                        # already in your cargo
            if q <= 0 or str(nm).lower() in keep:
                continue
            m3 = q * vol.get(tid, 0.0)
            rows.append({"system": name, "item": nm, "qty": q, "m3": m3, "value": q * adj.get(tid, 0.0), "per_m3": q * adj.get(tid, 0.0) / max(m3, 0.0001)})
    rows.sort(key=lambda d: -d["per_m3"])
    out = []
    for d in rows:
        if d["m3"] <= room + 1e-9:
            out.append(d)
            room -= d["m3"]
        if len(out) >= limit:
            break
    return out


def pickup_step(con, g, p, next_dest_name):
    """At a stop on a trip: the ONE step 'pick up the stock lying here' when there is some that fits (else ''). The trip continues afterwards."""
    cur = g.id_of(p.current_system)
    rows = [d for d in pickups(con, g, p, [cur]) if d["system"] == p.current_system]
    if not rows:
        return ""
    val = sum(d["value"] for d in rows)
    lines = [f"      {d['qty']:>9,} x {d['item']}  ({d['m3']:,.0f} m3)" for d in rows]
    return "\n".join([f"STEP: PICK UP STOCK in {p.current_system} (about {sum(d['m3'] for d in rows):,.0f} m3, worth about {val:,.0f} ISK)",
                      "   DO ONLY THIS: dock, open the item hangar and move these into your ship's cargo (consolidates your stock; it rides along):"] + lines
                     + [f"   LATER: the trip continues to {next_dest_name}; the stock is sold or delivered where it pays most"])


_BUY_RE = None
BUYSHOWN_KEY = "buyhere_shown"


def buy_here_step(con, g, p, text):
    """A trip step ('STEP: FLY to X') whose optional route trades include a BUY in the system you stand in: the buy comes FIRST, as its own step (flying on first would miss it).
    One item per step, each shown once (2 h): `stop` on it records the purchase (acquire), the next `next` gives the next buy or the flight. -> step text or ''."""
    import json
    import re
    import time
    global _BUY_RE
    if _BUY_RE is None:
        _BUY_RE = re.compile(r"^\s+buy ([\d,]+) x (.+?) at (.+?) \(-([\d,]+)\)(?:, sell at (.+?) \(\+([\d,]+)\) = \+([\d,]+) ISK)?")
    shown = _meta_json(con, BUYSHOWN_KEY)
    now = time.time()
    from .acquire import held, station_name
    for ln in text.split("\n"):
        m = _BUY_RE.match(ln)
        if not m or m.group(3).strip().lower() != str(p.current_system).lower():
            continue
        qty, item, cost = int(m.group(1).replace(",", "")), m.group(2).strip(), int(m.group(4).replace(",", ""))
        key = f"{item}@{p.current_system}"
        if now - shown.get(key, 0) < 2 * 3600 or held(con, item) >= qty:
            continue
        row = con.execute("SELECT o.location_id FROM orders o JOIN types t ON t.type_id=o.type_id WHERE t.name=? COLLATE NOCASE AND o.is_buy=0 AND o.system_id=? "
                          "ORDER BY o.price LIMIT 1", (item, g.id_of(p.current_system))).fetchone()
        loc = int(row[0]) if row else 0
        sname = station_name(con, loc) if loc else ""
        gain = f"; sells at {m.group(5)} for +{int(m.group(6).replace(',', '')):,} = +{int(m.group(7).replace(',', '')):,} ISK" if m.group(5) else ""
        head = f"STEP: ACQUIRE {qty:,} x {item} - BUY at {sname or p.current_system} (about {cost:,} ISK, a route trade{gain})"
        if loc:
            try:
                from .tradestep import STATION
                STATION[head] = loc
            except Exception:                                           # noqa: BLE001
                pass
        shown[key] = now
        con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (BUYSHOWN_KEY, json.dumps(shown)))
        con.commit()
        return "\n".join([head, f"   DO ONLY THIS: dock at {sname or p.current_system}, Market > {item} > Buy > the cheapest sell orders, {qty:,} unit(s). Check the live price first: if the margin is gone, skip it and run  python -m eve_profit next.",
                          "   LATER: then the flight on with it (the sale is at the far end)"])
    return ""
