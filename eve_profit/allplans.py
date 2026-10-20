"""EVERYTHING TO DO IN THE GAME, ONE LIST BY ISK PER MINUTE (the `next --plan` view). Every activity in activity_catalog.json (careers, missions, mining, hauling,
exploration, industry ...), the plans that are ready now, the agent reads and the blocked daily goals stand on the same list. For each: its ISK/min, whether you can do it NOW
or what is missing (skills, ship, tool, blueprint, LP: each prerequisite is a step the plan buys or trains on the way, see SHOPPING), and whether it is already MODELED
(3 timed runs) or still a guess. Collecting models and agent offers is worth ISK in itself, so an untimed activity is ranked at its expected rate PLUS its value of
information (catalog.INFO_WEIGHT x voi), the same yardstick `equal_footing` uses."""
from .health import record as _hrec
from .catalog import INFO_WEIGHT, MODELED_RUNS, RISK_HAIRCUT, status, voi
from .lookahead import act_rate

MAX_ROWS = 25


def rows(con, g, p, best_known, hull=None, owned=(), tools=None):
    """-> [{name, per_min, rate, state, ready, missing, kind}] best ISK/min first."""
    out = []
    for a in status(con, float(getattr(p, "wallet_isk", 0.0) or 0.0), hull, owned, tools):
        if a.get("blocked"):
            continue
        rate, src = act_rate(a)
        rate *= 1.0 - RISK_HAIRCUT.get(a.get("risk", "low"), 0.0)
        info = INFO_WEIGHT * voi(a, best_known) if a["state"] != "MODELED" else 0.0
        out.append({"name": a["name"], "per_min": (rate + info) / 60.0, "rate": rate, "info": info, "state": a["state"], "src": src, "ready": a["unlocked"],
                    "missing": a["missing"], "where": a.get("where"), "kind": "activity"})
    try:                                                                # blocked AIR daily goals (ship / tool missing)
        from .shopping import blocked_goals
        for b in blocked_goals(con, g, p):
            out.append({"name": "AIR daily goal: " + b["goal"], "per_min": b["per_min"], "rate": b["per_min"] * 60.0, "info": 0.0, "state": "DAILY", "src": "reward / time",
                        "ready": False, "missing": b["lines"] or [b["why"]], "where": None, "kind": "daily"})
    except Exception as _he:                                                   # noqa: BLE001
        _hrec('allplans', _he)
    out.sort(key=lambda r: -r["per_min"])
    return out


def lines(con, g, p, cands, hull=None, owned=(), tools=None):
    """-> text block for the long view."""
    best_known = min(max((c[0] for c in cands if c[0] != float("inf")), default=0.0), 5_000_000.0)
    rs = rows(con, g, p, best_known, hull, owned, tools)
    if not rs:
        return ""
    L = ["EVERYTHING BY ISK PER MINUTE (every career, plan and activity on one list; READY = doable now, otherwise what is missing is bought / trained on your way; "
         "an unmodeled one also counts its value of information, because collecting models and agent offers is worth ISK itself):"]
    for r in rs[:MAX_ROWS]:
        tag = "READY " if r["ready"] else "LATER "
        mod = {"MODELED": "modeled", "PARTIAL": "partly modeled", "UNMODELED": "not modeled yet (a guess)", "DAILY": "daily goal"}.get(r["state"], r["state"].lower())
        L.append(f"   {tag}{r['per_min']:>8,.0f} ISK/min  {r['name'][:46]:<46} {mod}" + (f"; +{r['info'] / 60:,.0f}/min for what timing it teaches" if r["info"] > 0 else ""))
        if not r["ready"]:
            L.append("            needs: " + "; ".join(str(m) for m in r["missing"][:4]))
        elif r["where"] and r["where"] != getattr(p, "current_system", None):
            L.append(f"            done in {r['where']}: when your route passes (agent offers there are read on the way)")
    if len(rs) > MAX_ROWS:
        L.append(f"   ... {len(rs) - MAX_ROWS} more (python -m eve_profit models)")
    L.append(f"   (MODELED = {MODELED_RUNS}+ of your own timed runs; agent reads and offers already join the plan list above at their own ISK/hr)")
    return "\n".join(L)
