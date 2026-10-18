"""The SHIP TREE as a table, from the game's own data: every ship on the market with its class, slots (high / mid / low, turret and launcher hardpoints), the skills
needed to fly it (type_skills, from the game data) and its cheapest price near you. `ships --refresh` reads slots and class from ESI once and keeps them; `ships` prints
the table; `upgrade` finds the hull that carries MORE tools at once (tools.fit_plan) than your best one at the lowest price per extra tool, which joins the shopping list."""
import json

from . import shipslots, skills, tools

KEY = "ship_catalog"
GROUPS = "group_names"
MAX_SHARE = 0.10


def _meta(con, key):
    try:
        r = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(r[0]) if r else {}
    except Exception:                                                   # noqa: BLE001
        return {}


def _put(con, key, d):
    con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, json.dumps(d)))
    con.commit()


def catalog(con):
    return _meta(con, KEY)


def candidates(con):
    """[(type_id, name)] of ships that have a sell order in the scanned markets (the ones you could buy)."""
    try:
        return con.execute("SELECT DISTINCT t.type_id, t.name FROM types t JOIN orders o ON o.type_id=t.type_id WHERE t.category_id=6 AND o.is_buy=0 ORDER BY t.name").fetchall()
    except Exception:                                                   # noqa: BLE001
        return []


def _group_name(con, esi, gid, names):
    if not gid:
        return ""
    if str(gid) in names:
        return names[str(gid)]
    try:
        nm = esi.get(f"/universe/groups/{gid}/")[0].get("name", "")
    except Exception:                                                   # noqa: BLE001
        nm = ""
    names[str(gid)] = nm
    return nm


def refresh(con, esi, log=print, limit=500):
    """Read slots + class of every candidate ship not yet in the catalog (one ESI call each, kept). -> number added."""
    cat, names, slots_all = catalog(con), _meta(con, GROUPS), _meta(con, shipslots.KEY)
    added = 0
    for tid, name in candidates(con):
        if str(tid) in cat or added >= limit:
            continue
        try:
            info = esi.type_info(tid)
        except Exception:                                               # noqa: BLE001
            continue
        sl = {shipslots.ATTR[a["attribute_id"]]: int(a["value"]) for a in info.get("dogma_attributes", []) if a["attribute_id"] in shipslots.ATTR}
        if "high" not in sl:
            continue
        cat[str(tid)] = {"name": name, "group": _group_name(con, esi, info.get("group_id"), names), "slots": sl}
        slots_all[str(tid)] = sl
        added += 1
        if added % 25 == 0:
            log(f"   ... {added} ships read")
    _put(con, KEY, cat)
    _put(con, GROUPS, names)
    _put(con, shipslots.KEY, slots_all)
    return added


def _prices(con, g, p, max_jumps=14):
    """{ship name: (price, jumps, system)}: the cheapest safe sell order in reach, a jump counted at the value of your time (same rule as acquire.sources), all in ONE query."""
    from .acquire import JUMP_VALUE_ISK, SAFE_SEC
    try:
        reach = g.reach(g.id_of(p.current_system), max_jumps, p.avoid_yellow)
        rows = con.execute("SELECT t.name, o.system_id, MIN(o.price) FROM orders o JOIN types t ON t.type_id=o.type_id "
                           "WHERE t.category_id=6 AND o.is_buy=0 AND o.volume_remain>=1 GROUP BY t.name, o.system_id").fetchall()
    except Exception:                                                   # noqa: BLE001
        return {}
    best = {}
    for name, sid, price in rows:
        if sid not in reach or g.sec[sid] < SAFE_SEC:
            continue
        cost = float(price) + reach[sid].jumps * JUMP_VALUE_ISK
        if name not in best or cost < best[name][0]:
            best[name] = (cost, float(price), reach[sid].jumps, g.name[sid])
    return {n: (v[1], v[2], v[3]) for n, v in best.items()}


def _flyable(con, tid, have):
    miss = skills.type_missing(con, int(tid), have)
    return (not miss), (skills.explain(con, miss) if miss else "")


def report(con, g, p, text=""):
    cat = catalog(con)
    if not cat:
        return "No ship data yet: run  python -m eve_profit scan  (prices) and then  python -m eve_profit ships --refresh  (reads slots and class from the game, once)."
    have, rows, prices = skills.have(con), [], _prices(con, g, p)
    for tid, d in cat.items():
        if text and text.lower() not in (d["name"] + " " + d["group"]).lower():
            continue
        ok, why = _flyable(con, tid, have)
        pr = prices.get(d["name"])
        plan = tools.fit_plan(d["slots"])
        rows.append((not ok, pr[0] if pr else 1e18, d, ok, why, pr, plan))
    rows.sort(key=lambda r: (r[0], r[1]))
    L = [f"{'ship':<22} {'class':<18} {'H/M/L':<7} {'tur/lau':<8} {'price':>12} {'jumps':>5}  can fly / carries at once"]
    for _, _, d, ok, why, pr, plan in rows[:60]:
        sl = d["slots"]
        carries = ", ".join(f"{n} x {t}" for t, n in plan) or "-"
        L.append(f"{d['name'][:22]:<22} {d['group'][:18]:<18} {sl.get('high', 0)}/{sl.get('mid', 0)}/{sl.get('low', 0):<3} {sl.get('turret', 0)}/{sl.get('launcher', 0):<6} "
                 + (f"{pr[0]:>12,.0f} {pr[1]:>5}" if pr else f"{'no price':>12} {'':>5}") + "  " + ("YES" if ok else f"needs {why[:40]}") + f"  | {carries}")
    L += ["", f"{len(rows)} ships ({len(cat)} read from the game). Filter by name or class:  ships --item Frigate   |   more ships:  scan, then  ships --refresh"]
    return "\n".join(L)


def upgrade(con, g, p, wallet=None):
    """-> {item, qty, why} for the hull you can fly that carries more tools at once than your best one, at the lowest ISK per extra tool, or None."""
    cat = catalog(con)
    if not cat:
        return None
    car = tools.carrier(con, p)
    base = sum(n for _t, n in car[2]) if car else 0
    wallet = float(wallet if wallet is not None else (getattr(p, "wallet_isk", 0.0) or 0.0))
    have, best, prices = skills.have(con), None, _prices(con, g, p)
    for tid, d in cat.items():
        total = sum(n for _t, n in tools.fit_plan(d["slots"]))
        if total <= base:
            continue
        ok, _why = _flyable(con, tid, have)
        if not ok:
            continue
        pr = prices.get(d["name"])
        if not pr or pr[0] > wallet * MAX_SHARE:
            continue
        score = pr[0] / (total - base)
        if best is None or score < best[0]:
            best = (score, d["name"], total, pr[0])
    if not best:
        return None
    return {"item": best[1], "qty": 1, "why": f"upgrade: carries {best[2]} tools at once (scanner + salvager + miners as the slots allow) against {base} on your best hull"}
