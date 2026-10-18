"""The TOOLS a career needs on the ship: a probe launcher + probes (scanning), a salvager (salvaging), mining lasers (mining), guns + ammo + a tank (combat).
A ship does an activity when the tool is FITTED, whatever its hull; a hull with more slots carries several tools at once (`fit_plan`). `fitted_now` reads what the ship
you fly carries, `have` counts what you own anywhere (hangars, parked ships, cargo), and `wishes` lists the tools still to buy for the careers worth doing."""
from . import shipslots

# tool id -> words that identify a fitted module, what to buy, slots one set uses ("launcher" = launcher hardpoint, "turret" = turret hardpoint)
TOOLS = {
    "scanning": {"label": "a probe launcher with probes", "words": ["probe launcher"],
                 "buy": [("Core Probe Launcher I", 1), ("Core Scanner Probe I", 8)], "uses": {"high": 1, "launcher": 1}},
    "salvaging": {"label": "a salvager", "words": ["salvager"], "buy": [("Salvager I", 1)], "uses": {"high": 1}},
    "mining": {"label": "mining lasers", "words": ["miner", "mining laser", "strip miner"], "buy": [("Miner I", 2)], "uses": {"high": 2, "turret": 2}},
}
PRIORITY = ["scanning", "salvaging", "mining"]          # when slots are short, in this order (cheapest to fit and useful on every trip first)


def fitted_now(con):
    """{tool: count of fitted modules} on the ship you fly (the `fitted` table is read from ESI at sync)."""
    out = {t: 0 for t in TOOLS}
    try:
        rows = con.execute("SELECT t.name, f.quantity FROM fitted f JOIN types t ON t.type_id=f.type_id WHERE f.flag LIKE '%Slot%'").fetchall()
    except Exception:                                                   # noqa: BLE001
        return out
    for name, q in rows:
        n = (name or "").lower()
        for t, d in TOOLS.items():
            if any(w in n for w in d["words"]):
                out[t] += int(q or 1)
    return out


def held_anywhere(con):
    """{tool: units of its modules you hold anywhere (hangars, parked ships)} counted by the first item of each tool's buy list."""
    out = {}
    for t, d in TOOLS.items():
        item = d["buy"][0][0]
        try:
            r = con.execute("SELECT COALESCE(SUM(i.quantity),0) FROM inventory i JOIN types t ON t.type_id=i.type_id WHERE t.name=? COLLATE NOCASE", (item,)).fetchone()
            out[t] = int(r[0] or 0)
        except Exception:                                               # noqa: BLE001
            out[t] = 0
    return out


def fit_plan(slots):
    """What one hull can carry AT THE SAME TIME: [(tool, how many modules)] in priority order, limited by high slots, turret and launcher hardpoints.
    slots: {high, turret, launcher} (None = unknown: nothing is promised)."""
    if not slots:
        return []
    hi, tu, la = int(slots.get("high", 0)), int(slots.get("turret", 0)), int(slots.get("launcher", 0))
    plan = []
    for t in PRIORITY:
        u = TOOLS[t]["uses"]
        n = 1
        if t == "mining":
            n = min(u["high"], hi, tu)                                  # up to two lasers, each takes a high slot and a turret hardpoint
        elif hi < u.get("high", 0) or la < u.get("launcher", 0) or tu < u.get("turret", 0):
            n = 0
        if n <= 0:
            continue
        plan.append((t, n))
        hi -= n
        tu -= n if t == "mining" else 0
        la -= u.get("launcher", 0)
    return plan


def carrier(con, p):
    """The hull you own (or fly) with the most high slots: (name, slots, fit plan) or None."""
    best = None
    for name, _sid, slots in shipslots.owned_hulls(con, p):
        if slots and (best is None or slots.get("high", 0) > best[1].get("high", 0)):
            best = (name, slots)
    if not best:
        return None
    return best[0], best[1], fit_plan(best[1])
