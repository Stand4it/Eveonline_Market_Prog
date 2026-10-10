"""AIR Daily Goals planner: the reward (445,000 ISK seen) is paid for ANY 2 of the 5 daily goals, so pick the cheapest pair.
Every goal is costed in minutes (travel included) and ISK to get it done; jumps are free when the trip is going there anyway.
Numbers marked '?' are guesses: edit the "plan" block of a goal in bonus_programs.json (minutes, cash, feasible, why_not) after you time one."""
import itertools

PER_JUMP_MIN = 3.0           # minutes per jump (same as agent_offers.json min_per_jump)
JUMPS_FREE_MIN = 1.0         # extra minutes the 3-jump goal costs when you are travelling that far anyway

GUN_WORDS = ("blaster", "autocannon", "railgun", "laser", "artillery", "launcher", "pulse", "beam")
SKIP_WORDS = ("probe", "mining", "salvag", "cargo scanner", "survey", "tractor", "analyzer")


def _q(con, sql, args=()):
    try:
        return con.execute(sql, args).fetchall()
    except Exception:                                                   # noqa: BLE001
        return []


def _fitted_names(con):
    return [(r[0] or "").lower() for r in _q(con, "SELECT t.name FROM fitted f JOIN types t ON t.type_id=f.type_id")]


def _min_ask(con, name):
    r = _q(con, "SELECT MIN(o.price) FROM orders o JOIN types t ON t.type_id=o.type_id WHERE t.name=? COLLATE NOCASE AND o.is_buy=0", (name,))
    return float(r[0][0]) if r and r[0][0] else None


def _has_skill(con, name):
    r = _q(con, "SELECT s.level FROM character_skills s JOIN types t ON t.type_id=s.skill_id WHERE t.name=? COLLATE NOCASE", (name,))
    return bool(r and r[0][0] >= 1)


def _far_places(con, mining=None, offers=None):
    """Known places 3+ jumps away that are worth going to anyway: (rate or 0, label, jumps)."""
    out = []
    try:
        from .nextstep import offers_rows
        for rate, net, minutes, o, tags in offers if offers is not None else offers_rows(con):
            if o.get("jumps", 0) >= 3:
                out.append((rate, f"{o['agent']} (agent mission, {o['jumps']} jumps)", o["jumps"]))
    except Exception:                                                   # noqa: BLE001
        pass
    try:
        from .mining_sites import rank_sites
        for s in mining if mining is not None else rank_sites(con):
            if s["jumps"] >= 3:
                out.append((0.0, f"{s['system']} (mining, {s['jumps']} jumps)", s["jumps"]))
    except Exception:                                                   # noqa: BLE001
        pass
    out.sort(key=lambda x: -x[0])
    return out


def build_option(con):
    """Cheapest build you can start from a blueprint you own: materials already in the hangar cost nothing."""
    best = None
    for bp, name in _q(con, "SELECT b.blueprint_id, t.name FROM my_blueprints b LEFT JOIN types t ON t.type_id=b.blueprint_id"):
        mats = _q(con, "SELECT m.material_id, m.quantity, t.name FROM bp_materials m LEFT JOIN types t ON t.type_id=m.material_id WHERE m.blueprint_id=?", (bp,))
        if not mats:
            continue
        cash, missing, buy_lines = 0.0, False, []
        for mid, qty, mname in mats:
            have = _q(con, "SELECT COALESCE(SUM(quantity),0) FROM inventory WHERE type_id=?", (mid,))[0][0]
            need = max(0, qty - have)
            if need:
                ask = _min_ask(con, mname or "")
                if ask is None:
                    missing = True
                    break
                cash += ask * need
                buy_lines.append(f"{need:,} x {mname}")
        if missing:
            continue
        if best is None or cash < best["cash"]:
            best = {"cash": cash, "bp": name or str(bp), "buy": buy_lines}
    if not best:
        return {"goal": "Manufacture an Item", "ok": False, "why_not": "no blueprint you own can be built from materials on the scanned market", "minutes": 0, "cash": 0}
    minutes = 4.0 + (4.0 if best["buy"] else 0.0)
    how = f"Industry > build 1 run of {best['bp']}" + (" (buy first: " + ", ".join(best["buy"]) + ")" if best["buy"] else " (all materials already in your hangar)")
    return {"goal": "Manufacture an Item", "ok": True, "minutes": minutes, "cash": best["cash"], "how": how, "jumps_away": 0}


def scan_option(con):
    fitted = _fitted_names(con)
    launcher = any("probe launcher" in n for n in fitted)
    skill = _has_skill(con, "Astrometrics")
    if not skill:
        return {"goal": "Scan 5 Signatures", "ok": False, "why_not": "needs the Astrometrics skill (train I, about 5 min of queue)", "minutes": 0, "cash": 0}
    probes = (_min_ask(con, "Core Scanner Probe I") or 15000.0) * 8
    cash = probes if launcher else probes + 150000.0
    how = "fit a Probe Launcher and 8 probes in your Imicus" if not launcher else "scan down 5 signatures in Rotonos or next door"
    return {"goal": "Scan 5 Signatures", "ok": True, "minutes": 25.0 if launcher else 35.0, "cash": cash, "how": how + "  (?)", "jumps_away": 0}


def destroy_option(con):
    fitted = _fitted_names(con)
    guns = [n for n in fitted if any(w in n for w in GUN_WORDS) and not any(w in n for w in SKIP_WORDS)]
    try:
        from .mining_sites import sites
        rat = sorted([s for s in sites() if s.get("sec", 0) >= 0.5 and s.get("hostiles") not in (None, "", "?", "unknown")], key=lambda s: s["jumps"])
    except Exception:                                                   # noqa: BLE001
        rat = []
    jumps = rat[0]["jumps"] if rat else 4
    where = f"{rat[0]['system']} ({rat[0]['hostiles']} rats, {jumps} jumps)" if rat else f"a system with rats ({jumps} jumps?)"
    minutes = 40.0 + 2 * jumps * PER_JUMP_MIN
    if guns:
        return {"goal": "Destroy 25 non-capsuleers", "ok": True, "minutes": minutes, "cash": 20000.0,
                "how": f"fly to {where} and kill 25 rats with your fitted guns (ammo ~20k)  (?)", "jumps_away": jumps}
    return {"goal": "Destroy 25 non-capsuleers", "ok": True, "minutes": minutes + 20, "cash": 120000.0,
            "how": f"you have no guns fitted: buy guns + ammo (~120k?), then fly to {where} and kill 25 rats  (?)", "jumps_away": jumps}


def repair_option(con):
    return {"goal": "Armor Repair other Capsuleers", "ok": False, "minutes": 0, "cash": 0,
            "why_not": "needs a remote armor repairer AND other players in a fleet to repair 2,500: not solo, not routed"}


def jumps_option(con, places=None):
    places = _far_places(con) if places is None else places
    dest = places[0][1] if places else "Manifest (epic arc agent, 3 jumps)"
    return {"goal": "Complete 3 Jumps", "ok": True, "minutes": 3 * PER_JUMP_MIN, "cash": 0.0, "jumps_away": 0,
            "how": f"fly to {dest}: that trip IS the 3 jumps (stay in 0.5+ space)", "dest": dest}


def options(con, places=None):
    return [jumps_option(con, places), build_option(con), scan_option(con), destroy_option(con), repair_option(con)]


def plan(con, reward=445000.0, free_ride=False, places=None):
    """Best pair of goals by net ISK per hour. free_ride=True when your next task already goes 3+ jumps."""
    opts = options(con, places)
    ok = [o for o in opts if o["ok"]]
    best = None
    for a, b in itertools.combinations(ok, 2):
        minutes = a["minutes"] + b["minutes"]
        for x, y in ((a, b), (b, a)):                                   # jumps are free when the other goal's trip goes 3+ jumps anyway
            if x["goal"] == "Complete 3 Jumps" and (y.get("jumps_away", 0) >= 3 or free_ride):
                minutes = y["minutes"] + JUMPS_FREE_MIN
        cash = a["cash"] + b["cash"]
        rate = (reward - cash) * 60.0 / max(minutes, 1.0)
        if best is None or rate > best["rate"]:
            best = {"pair": (a, b), "minutes": minutes, "cash": cash, "rate": rate, "net": reward - cash}
    return {"best": best, "options": opts, "reward": reward}


def format_plan(pl, progress=None):
    progress = progress or {}
    b = pl["best"]
    if not b:
        return "STEP: AIR DAILY GOALS - no pair of goals is doable right now (see the list below)"
    a1, a2 = b["pair"]
    L = [f"STEP: AIR DAILY GOALS - about {pl['reward']:,.0f} ISK for any 2 of the 5 goals (resets daily)",
         f"   BEST PAIR: {a1['goal']} + {a2['goal']}   ~{b['minutes']:.0f} min, ~{b['cash']:,.0f} ISK to do it = ~{b['rate']:,.0f} ISK/hr"]
    for o in (a1, a2):
        L.append(f"   DO: {o['goal']} {progress.get(o['goal'], '')}: {o['how']}")
    L.append("   All five (minutes / ISK to do it):")
    for o in sorted(pl["options"], key=lambda o: (not o["ok"], o["minutes"])):
        mark = "<<" if o in b["pair"] else "  "
        if o["ok"]:
            L.append(f"   {mark} {o['goal']:<30} {progress.get(o['goal'], ''):<8} ~{o['minutes']:.0f} min, ~{o['cash']:,.0f} ISK")
        else:
            L.append(f"      {o['goal']:<30} {progress.get(o['goal'], ''):<8} NOT ROUTED: {o['why_not']}")
    L.append("   Check the Opportunities > AIR Daily Goals window. Items marked (?) are guesses: time it and the model learns.")
    return "\n".join(L)
