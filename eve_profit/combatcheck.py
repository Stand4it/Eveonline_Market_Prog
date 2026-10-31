"""COMBAT CHECK (owner 2026-10-28): your fit's DPS / EHP / repair against each mission level, by the 99% rule (win_assessment: the chance of losing
the ship in a one-hour session must be 1% or less). For a level the fit fails it says the DPS and EHP that would pass, and the CHEAPEST fit
from the modules in combat_modules.json (owned ones free) that passes: guns in the turret slots, damage / plate / damage control / repairer
in the low slots. Module numbers are estimates scaled to your measured DPS (skills); after fitting, show the fitting window and
`combatfit` replaces the estimate with the real numbers.
CAPACITOR (owner 2026-10-28): guns and repairers use capacitor. When a fit uses more than the capacitor recharges, it runs dry part way through
a wave and the guns and repairers then only run as often as the recharge allows, so the fit is judged on those lower numbers. A cap module
(Capacitor Power Relay low, Cap Recharger mid) is only bought when the cheapest passing fit needs one."""
import itertools
import json
import os

from .health import record as _hrec

_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "combat_modules.json")
P_MAX = 0.01                  # the 99% rule
K_MIN, K_MAX = 0.7, 1.6       # skills + hull bonus can scale the table's turret DPS this far (a destroyer's 10%/level hybrid bonus and gunnery skills)
LEVEL1 = {"name": "Level 1 security mission", "enemy_ehp": 5000.0, "threat_dps": 25.0, "waves_per_hour": 6.0, "session_hours": 1.0, "p_loss_per_hour": 0.0002, "min_dps": 40.0}
RATTING = "High-sec belt ratting (frigate)"
RESULTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "combat_results.json")


def results():
    """Real fights you reported (scripts/combat_result.py): [{date, level, mission, dps, ehp, tank, won}]."""
    try:
        with open(RESULTS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def calibrate(level, req, res=None):
    """A real win beats the guessed numbers (owner 2026-10-31: an L1 cleared with 18.5 DPS / 4,149 EHP that the model gave ~0%).
    With wins and no losses at this level: the weakest winning fit sets min_dps, and the threat is lowered until that fit passes the
    99% rule. Any loss at this level keeps the guessed numbers."""
    rs = [r for r in (results() if res is None else res) if str(r.get("level")) == str(level)]
    wins = [r for r in rs if r.get("won")]
    if not wins or any(not r.get("won") for r in rs):
        return req
    req = dict(req)
    w = min(wins, key=lambda r: (r["dps"], r["ehp"]))
    req["min_dps"] = min(float(req.get("min_dps", 0) or 0), w["dps"])
    lo, hi = 0.0, float(req["threat_dps"])                              # the highest threat at which the winning fit still passes
    if p_lose(req, w["dps"], w["ehp"], w.get("tank", 0)) > P_MAX:
        for _ in range(60):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if p_lose(dict(req, threat_dps=mid), w["dps"], w["ehp"], w.get("tank", 0)) <= P_MAX else (lo, mid)
        req["threat_dps"] = lo
    req["calibrated"] = f"{len(wins)} real win(s)"
    return req


def _table():
    try:
        with open(_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def modules():
    return _table().get("modules", {})


def hull_cap(p, hull=""):
    """{cap_gj, recharge_s, prop_cap_s} for the hull: the table's estimate, with the capacitor size from `combatfit --cap` when you gave it."""
    hulls = _table().get("hulls", {})
    name = (hull or getattr(p, "ship_name", "") or "").lower()
    d = dict(hulls.get("default") or {"cap_gj": 400.0, "recharge_s": 200.0, "prop_cap_s": 0.9})
    for h, v in hulls.items():
        if h != "default" and h.lower() in name:
            d.update(v)
    for h, st in (getattr(p, "ships", {}) or {}).items():
        if h and h.lower() in name and st.get("cap_gj"):
            d["cap_gj"] = float(st["cap_gj"])
    return d


def cap_effect(cap_gj, recharge_s, use, ttk):
    """(share of the time guns and repairers can run over one wave of ttk seconds, seconds until the capacitor is empty or None when stable).
    Peak recharge is 2.5 x size / recharge time; while it drains the recharge averages about 60% of that, once empty about 80% of it."""
    peak = 2.5 * cap_gj / max(recharge_s, 1.0)
    if use <= peak or use <= 0:
        return 1.0, None
    empty = cap_gj / max(use - 0.6 * peak, 1e-9)
    if ttk <= empty:
        return 1.0, empty
    return (empty + (ttk - empty) * min(1.0, 0.8 * peak / use)) / ttk, empty


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
    return {k: calibrate(k, v) for k, v in out.items()}


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


def _killboard(con, hull_name):
    """owner 2026-10-30: (can(module name) -> your skills fit it, risk(module name) -> killboard factor >= 1 for the hull you fly; fitdb.py).
    No skills synced or no killmails read: everything allowed, every factor 1."""
    try:
        from . import fitdb, skills
        have = skills.have(con)
        hull = fitdb.type_id(con, hull_name) if hull_name else None
        rk = fitdb.module_risk(con, hull) if hull else {}
    except Exception as _he:                                            # noqa: BLE001
        _hrec('combatcheck', _he)
        return (lambda n: True), (lambda n: 1.0)
    ids = {}

    def tid(n):
        if n not in ids:
            try:
                ids[n] = fitdb.type_id(con, n)
            except Exception:                                           # noqa: BLE001
                ids[n] = None
        return ids[n]

    def can(n):
        return not have or tid(n) is None or fitdb.usable(con, tid(n), have)[0]
    return can, (lambda n: rk.get(tid(n), 1.0))


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
    can, risk = _killboard(con, _n)
    guns = [n for n, d in mods.items() if d.get("slot") == "turret" and can(n)]
    low = [n for n, d in mods.items() if d.get("slot") == "low" and can(n)] + [None]     # None = leave the slot empty
    mid = [n for n, d in mods.items() if d.get("slot") == "mid" and can(n)] + [None]
    mids = max(0, int(sl.get("mid", 0) or 0) - 1)                       # one mid slot keeps the afterburner
    hc = hull_cap(p, _n)
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
            for fill, combo in ((f, lo + mi) for f in (True, False) for lo in itertools.combinations_with_replacement(low, lows)
                                for mi in itertools.combinations_with_replacement(mid, mids)):
                counts = {m: combo.count(m) for m in set(combo) if m is not None}
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
                use = float(mods[gun].get("cap", 0.0)) * n + float(hc.get("prop_cap_s", 0.0))
                spare = turrets - n if fill else 0                       # the other turret slots take guns you already own (free) - or stay empty: guns cost capacitor
                for og in sorted((x for x in guns if x != gun and owned_n(x)), key=lambda x: -float(mods[x]["dps"])):
                    u = min(spare, owned_n(og))
                    if u > 0:
                        dps += float(mods[og]["dps"]) * u * k
                        use += float(mods[og].get("cap", 0.0)) * u
                        items.append((og, u, 0.0))
                        spare -= u
                ehp, rep_, rmult = ehp0, 0.0, 1.0
                for m, q in counts.items():
                    d = mods[m]
                    use += float(d.get("cap", 0.0)) * q
                    for i in range(q):                                   # stacking: each further copy counts less
                        f = 0.87 ** (i * i)
                        dps *= 1 + (float(d.get("dps_mult", 1.0)) - 1) * f
                        ehp *= 1 + (float(d.get("ehp_mult", 1.0)) - 1) * f
                        ehp += float(d.get("ehp_add", 0.0))
                        rep_ += float(d.get("tank_add", 0.0))
                        rmult *= 1 + (float(d.get("recharge_mult", 1.0)) - 1) * f
                share, empty = 1.0, None                                 # capacitor: runs dry part way through a wave -> guns and repairers slow down
                for _ in range(2):
                    share, empty = cap_effect(hc["cap_gj"], hc["recharge_s"] * rmult, use, req["enemy_ehp"] / max(dps * share, 1e-9))
                dps_e, tank = dps * share, tank0 + rep_ * share
                pl = p_lose(req, dps_e, ehp, tank)
                ok_ = passes(req, dps_e, ehp, tank)
                kb = 1.0
                for m_, q_, _c in items:
                    kb *= risk(m_)
                kb = min(kb, 2.0)
                key = (0 if ok_ else 1, cost * kb if ok_ else pl, cost)          # killboard: modules that die to NPCs on this hull more than average weigh as dearer
                if best is None or key < best["key"]:
                    best = {"key": key, "passes": ok_, "cost": cost, "items": items, "kb": kb, "dps": dps_e, "ehp": ehp, "tank": tank, "p": pl,
                            "cap_use": use, "cap_regen": 2.5 * hc["cap_gj"] / (hc["recharge_s"] * rmult), "cap_empty": empty, "cap_share": share}
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


def _cap_text(bf):
    if bf.get("cap_empty") is None:
        return f"capacitor: uses {bf['cap_use']:.1f} GJ/s, recharges up to {bf['cap_regen']:.1f} -> stable"
    if bf["cap_share"] >= 0.999:
        return f"capacitor: uses {bf['cap_use']:.1f} GJ/s vs {bf['cap_regen']:.1f} recharge; lasts ~{bf['cap_empty']:.0f}s, longer than a wave -> fine (refills between waves)"
    return (f"capacitor: uses {bf['cap_use']:.1f} GJ/s vs {bf['cap_regen']:.1f} recharge; empty after ~{bf['cap_empty']:.0f}s, "
            f"then guns and repairers run {100 * bf['cap_share']:.0f}% of the time (the numbers above include this)")


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
            L.append("         " + _cap_text(bf))
        elif bf:
            L.append(f"         no fit from combat_modules.json passes on this hull (best: win {100 * (1 - bf['p']):.1f}%): it needs a bigger ship or more skills")
    L.append("   Capacitor (estimate): fits above are judged on what they can keep running. After fitting, the fitting window shows 'stable' or how long it lasts; send it.")
    return "\n".join(L)
