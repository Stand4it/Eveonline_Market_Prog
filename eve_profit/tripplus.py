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


def cheap_needs(con, g, p, path, min_save=0.20, min_isk=3000.0):
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
            out.append(f"need anyway: {short:,} x {rule['item']} is ~{prices[s_best]:,.0f} each at {g.name[s_best]} on the route (here {local:,.0f}): buy there, saves ~{save:,.0f} ISK")
    return out


def extras(con, g, p, dest, m3=0.0):
    out = {"lines": [], "isk": 0.0, "minutes": 0.0}
    if g is None or p is None or not dest:
        return out
    path = _route(g, p, dest)
    if not path:
        return out
    out["lines"] += _agents(g, path)
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
