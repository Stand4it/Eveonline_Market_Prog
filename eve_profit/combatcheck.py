"""COMBAT CHECK (owner 2026-10-28): your fit's DPS / EHP / repair against each mission level, by the 99% rule (win_assessment: the chance of losing
the ship in a one-hour session must be 1% or less). For a level the fit fails it says the DPS and EHP that would pass, and the CHEAPEST fit
from the modules in combat_modules.json (owned ones free) that passes: guns in the turret slots, damage / plate / damage control / repairer
in the low slots. Module numbers are estimates scaled to your measured DPS (skills); after fitting, show the fitting window and
`combatfit` replaces the estimate with the real numbers."""
import itertools
import json
import os

from .health import record as _hrec

_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "combat_modules.json")
P_MAX = 0.01                  # the 99% rule
K_MIN, K_MAX = 0.7, 1.6       # skills + hull bonus can scale the table's turret DPS this far (a destroyer's 10%/level hybrid bonus and gunnery skills)
LEVEL1 = {"name": "Level 1 security mission", "enemy_ehp": 5000.0, "threat_dps": 25.0, "waves_per_hour": 6.0, "session_hours": 1.0, "p_loss_per_hour": 0.0002, "min_dps": 40.0}
RATTING = "High-sec belt ratting (frigate)"


def modules():
    try:
        with open(_FILE, encoding="utf-8") as f:
            return json.load(f)["modules"]
    except (OSError, ValueError, KeyError):
        return {}


def requirements(con):
    """{level: requirement row} for 1..4 and 'ratting' (the activities table; level 1 from LEVEL1)."""
    out = {1: dict(LEVEL1)}
    try:
        for r in con.execute("SELECT * FROM activities WHERE kind='combat'"):
            d = dict(r)
            if d.get("agent_level"):
                out[int(d["agent_level"])] = d
            elif d["name"] == RATTING:
                out["ratting"] = d
    except Exception as _he:                                            # noqa: BLE001
        _hrec('combatcheck', _he)
    return out


def level_of(goal_id=None, offer=None):
    """Mission level a goal needs: an offer's level, a catalog id's level, ratting / anomalies = 'ratting', else 2."""
    if offer is not None:
        import re
        m = re.search(r"\(\w+, L?(\d)", offer.get("agent", "") or "")       # 'Name (Security, 2, ...)' or 'Name (Security, L1, ...)'
        try:
            return int(offer.get("level") or (m.group(1) if m else 1))
        except (TypeError, ValueError):
            return 1
    ids = {"agent_l1_security": 1, "agent_l2_security": 2, "agent_l3_security": 3, "agent_l4_security": 4, "ratting": "ratting", "combat_anomalies": "ratting"}
    return ids.get(goal_id, 2)


def numbers(p):
    """(dps, ehp, tank) of the ship you fly: the profile's own numbers, else the `combatfit` numbers saved for its hull (the ship name holds the hull)."""
    if getattr(p, "combat_dps", 0) and getattr(p, "ship_ehp", 0):
        return float(p.combat_dps), float(p.ship_ehp), float(getattr(p, "ship_tank_dps", 0.0) or 0.0)
    name = (getattr(p, "ship_name", "") or "").lower()
    for hull, st in (getattr(p, "ships", {}) or {}).items():
        if hull and hull.lower() in name and st.get("combat_dps") and st.get("ship_ehp"):
            return float(st["combat_dps"]), float(st["ship_ehp"]), float(st.get("ship_tank_dps", 0.0) or 0.0)
    return 0.0, 0.0, 0.0


def p_lose(req, dps, ehp, tank):
    """Chance to lose the ship in one session (combat.win_assessment's model)."""
    if dps <= 0 or ehp <= 0:
        return 1.0
    ttk = req["enemy_ehp"] / dps
    dmg = max(0.0, req["threat_dps"] - tank) * ttk
    margin = float("inf") if dmg <= 0 else ehp / dmg
    p_wave = 0.0 if margin == float("inf") else 1 / (1 + margin ** 4)
    waves = max(1.0, req["waves_per_hour"] * req["session_hours"])
    return min(1.0, 1 - (1 - p_wave) ** waves + req["p_loss_per_hour"] * req["session_hours"])


def passes(req, dps, ehp, tank):
    return dps >= float(req.get("min_dps", 0) or 0) and p_lose(req, dps, ehp, tank) <= P_MAX


def _solve(f, lo, hi):
    """Smallest x in [lo, hi] with f(x) True (f monotone), or None."""
    if not f(hi):
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if f(mid) else (mid, hi)
    return hi


def needed(req, dps, ehp, tank):
    """(DPS that passes at your EHP, EHP that passes at your DPS) or None each when no value up to a big bound does."""
    nd = _solve(lambda x: passes(req, x, ehp, tank), 1.0, 20000.0) if ehp > 0 else None
    ne = _solve(lambda x: passes(req, dps, x, tank), 1.0, 5_000_000.0) if dps >= float(req.get("min_dps", 0) or 0) else None
    return nd, ne


def _hull_slots(con, p):
    try:
        from .shipslots import owned_hulls
        for n, sid, sl in owned_hulls(con, p):
            if sid is None and sl:
                return n, sl
    except Exception as _he:                                            # noqa: BLE001
        _hrec('combatcheck', _he)
    return "", {}


def _price(con, g, p, item, qty):
    """ISK to get qty x item: owned units free, the rest at the cheapest safe ask in reach; None when none is for sale."""
    from .acquire import held, sources
    need = max(0, qty - held(con, item))
    if need == 0:
        return 0.0
    src = sources(con, g, p, item, need, limit=2) if g is not None else []
    return src[0]["price"] * need if src else None


def _fitted_turret_dps(con, mods):
    """Estimated DPS of the turrets on the ship now (to scale the module estimates to your skills)."""
    try:
        rows = con.execute("SELECT t.name, f.quantity FROM fitted f JOIN types t ON t.type_id=f.type_id WHERE f.flag LIKE 'HiSlot%'").fetchall()
    except Exception:                                                   # noqa: BLE001
        return 0.0
    return sum(float(mods[n]["dps"]) * int(q or 1) for n, q in rows if n in mods and mods[n].get("slot") == "turret")


def best_fit(con, g, p, req):
    """The cheapest fit that passes `req` -> {cost, items [(name, qty, isk)], dps, ehp, tank, p} or the best-odds fit with passes=False, or None."""
    mods = modules()
    dps0, ehp0, tank0 = numbers(p)
    if not mods or not dps0:
        return None
    _n, sl = _hull_slots(con, p)
    turrets, lows = int(sl.get("turret", 0) or 0), int(sl.get("low", 0) or 0)
    if not turrets:
        return None
    est = _fitted_turret_dps(con, mods)
    k = dps0 / est if est > 0 else 1.0                                  # your skills and hull bonus relative to the table
    k = min(max(k, K_MIN), K_MAX)                                       # the fitted list lags an hour (ESI): 23 DPS from 8 guns read against 2 guns gave x5
    guns = [n for n, d in mods.items() if d.get("slot") == "turret"]
    low = [n for n, d in mods.items() if d.get("slot") == "low"]
    price = {}

    def pr(item, qty):
        if (item, qty) not in price:
            price[(item, qty)] = _price(con, g, p, item, qty)
        return price[(item, qty)]

    from .acquire import held
    owned = {}

    def owned_n(item):
        if item not in owned:
            try:
                owned[item] = held(con, item) if con is not None else 0
            except Exception:                                           # noqa: BLE001
                owned[item] = 0
        return owned[item]

    best = None
    for gun in guns:
        for n in range(1, turrets + 1):
            c_gun = pr(gun, n)
            if c_gun is None:
                continue
            for combo in itertools.combinations_with_replacement(low, lows):
                counts = {m: combo.count(m) for m in set(combo)}
                cost, items, ok = c_gun, [(gun, n, c_gun)], True
                for m, q in counts.items():
                    c = pr(m, q)
                    if c is None:
                        ok = False
                        break
                    cost += c
                    items.append((m, q, c))
                if not ok:
                    continue
                dps = float(mods[gun]["dps"]) * n * k
                spare = turrets - n                                      # the other turret slots take guns you already own (free)
                for og in sorted((x for x in guns if x != gun and owned_n(x)), key=lambda x: -float(mods[x]["dps"])):
                    use = min(spare, owned_n(og))
                    if use > 0:
                        dps += float(mods[og]["dps"]) * use * k
                        items.append((og, use, 0.0))
                        spare -= use
                ehp, tank = ehp0, tank0
                for m, q in counts.items():
                    d = mods[m]
                    for i in range(q):                                   # stacking: each further copy counts less
                        f = 0.87 ** (i * i)
                        dps *= 1 + (float(d.get("dps_mult", 1.0)) - 1) * f
                        ehp *= 1 + (float(d.get("ehp_mult", 1.0)) - 1) * f
                        ehp += float(d.get("ehp_add", 0.0))
                        tank += float(d.get("tank_add", 0.0))
                pl = p_lose(req, dps, ehp, tank)
                ok_ = passes(req, dps, ehp, tank)
                key = (0 if ok_ else 1, cost if ok_ else pl, cost)
                if best is None or key < best["key"]:
                    best = {"key": key, "passes": ok_, "cost": cost, "items": items, "dps": dps, "ehp": ehp, "tank": tank, "p": pl}
    return best


def missing_items(con, g, p, level):
    """[(item, qty)] still to buy for the cheapest fit that passes `level` ([] when your fit passes or no fit can)."""
    reqs = requirements(con)
    req = reqs.get(level) or reqs.get(2)
    dps, ehp, tank = numbers(p)
    if not req or (dps and passes(req, dps, ehp, tank)):
        return []
    bf = best_fit(con, g, p, req)
    if not bf or not bf["passes"]:
        return []
    from .acquire import held
    return [(n, q - held(con, n)) for n, q, _c in bf["items"] if held(con, n) < q]


def reachable(con, g, p, level):
    """False only when your numbers are known and no fit of combat_modules.json on the hull you fly passes `level` (a bigger ship or skills first)."""
    reqs = requirements(con)
    req = reqs.get(level) or reqs.get(2)
    dps, ehp, tank = numbers(p)
    if not req or not dps or passes(req, dps, ehp, tank):
        return True
    bf = best_fit(con, g, p, req)
    return bool(bf and bf["passes"]) or bf is None


def ready(con, g, p, level=1):
    """True when the numbers you showed pass `level` by the 99% rule."""
    reqs = requirements(con)
    req = reqs.get(level) or reqs.get(2)
    dps, ehp, tank = numbers(p)
    return bool(req) and passes(req, dps, ehp, tank)


def report(con, g, p):
    """Text for `python -m eve_profit combatcheck`."""
    dps, ehp, tank = numbers(p)
    if not dps:
        return ("No combat numbers for the ship you fly yet. Open the Fitting window, send me a screenshot (DPS, EHP), or run\n"
                '   python -m eve_profit combatfit --ship "<hull>" --dps <DPS> --ehp <EHP> [--tank <repair hp/s>]')
    L = [f"COMBAT CHECK for {getattr(p, 'ship_name', '') or 'your ship'}: {dps:,.1f} DPS, {ehp:,.0f} EHP, {tank:,.0f} repair/s  (rule: lose the ship in under 1% of sessions)"]
    reqs = requirements(con)
    for lv in (1, "ratting", 2, 3, 4):
        req = reqs.get(lv)
        if not req:
            continue
        pl = p_lose(req, dps, ehp, tank)
        name = req["name"]
        if passes(req, dps, ehp, tank):
            L.append(f"   PASS  {name}: win {100 * (1 - pl):.2f}%")
            continue
        nd, ne = needed(req, dps, ehp, tank)
        why = [f"with no other change it needs {max(nd, float(req.get('min_dps', 0) or 0)):,.0f} DPS" if nd else "no DPS alone is enough at your EHP and repair"]
        if ne:
            why.append(f"or {ne:,.0f} EHP at your DPS")
        why.append("(a repairer lowers the DPS needed: see the fit below)")
        L.append(f"   FAIL  {name}: win {100 * (1 - pl):.1f}%; " + " ".join(why))
        bf = best_fit(con, g, p, req)
        if bf and bf["passes"]:
            L.append(f"         cheapest fit that passes (~{bf['cost']:,.0f} ISK to buy; owned modules free): "
                     + ", ".join(f"{q} x {n}" + (" (owned)" if c == 0 else f" ~{c:,.0f}") for n, q, c in bf["items"]))
            L.append(f"         estimate: {bf['dps']:,.0f} DPS, {bf['ehp']:,.0f} EHP, {bf['tank']:,.0f}/s -> win {100 * (1 - bf['p']):.2f}%  (show me the fit after fitting it)")
        elif bf:
            L.append(f"         no fit from combat_modules.json passes on this hull (best: win {100 * (1 - bf['p']):.1f}%): it needs a bigger ship or more skills")
    L.append("   Capacitor is not modeled: if the fitting window says the capacitor runs dry in under a minute, the guns stop; send it and I will check.")
    return "\n".join(L)
