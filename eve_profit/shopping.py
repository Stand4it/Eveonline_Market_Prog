"""SHOPPING AS PART OF THE PLAN: the ships, modules and ammo the plan needs are bought where they are CHEAPEST (buy vs build, detours counted at the value of
your time), at the moment your route is in that place, and every later plan then uses what you own. A wish is one of: a missing piece of the combat kit (hull, guns,
ammo, tank: combatprep) or an extra you list in ship_fits.json under "wishlist" ([{"item": "Expanded Cargohold I", "qty": 1, "why": "more m3 for hauls"}]: an upgrade to a ship you own).
`candidates` offers a purchase as a step only when THIS place is the cheapest source; `lines` lists every wish with its cheapest source for `next --plan`."""
import json
import os

_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ship_fits.json")
MAX_SHARE = 0.10            # never spend more than a tenth of the wallet on one opportunistic purchase
RATE_EDGE = 1.2             # a purchase at the best place ranks just above the best step (so the 15% no-flip rule lets it through)


def _extras():
    try:
        with open(_FILE, encoding="utf-8") as f:
            return json.load(f).get("wishlist", [])
    except (OSError, ValueError):
        return []


def wishes(con, p):
    """-> [{item, qty, why}] still missing, in the order they are needed."""
    from . import acquire, combatprep
    out = []
    try:
        k = combatprep.kit()
        s = combatprep.state(con, p)
        if not any(h.lower() in (s["hull"] or "").lower() for h in k["hulls"]) and not any(any(h.lower() in n.lower() for h in k["hulls"]) for n, _sid in s["ships"]):
            out.append({"item": k["hulls"][0], "qty": 1, "why": "combat hull (you own none)"})
        have_t = sum(q for n, q in s["fitted"] if any(w in n.lower() for w in k["turret_words"]))
        have_t += sum(sum(q for _sid, q in rows) for n, rows in s["stock"].items() if any(w in n.lower() for w in k["turret_words"]) and "civilian" not in n.lower())
        if have_t < k["turrets"]:
            out.append({"item": k["turret_buy"], "qty": k["turrets"] - have_t, "why": "guns for the combat fit"})
        if acquire.held(con, k["ammo"]) < k["ammo_qty"]:
            out.append({"item": k["ammo"], "qty": k["ammo_qty"] - acquire.held(con, k["ammo"]), "why": "ammo for the guns"})
        has_tank = any(any(w in n.lower() for w in k["tank_words"]) for n, _q in s["fitted"]) or any(
            any(w in n.lower() for w in k["tank_words"]) for n in s["stock"]) or acquire.held(con, k["tank_buy"]) >= 1
        if not has_tank:
            out.append({"item": k["tank_buy"], "qty": 1, "why": "armor repairer (tank)"})
    except Exception:                                                   # noqa: BLE001
        pass
    for w in _extras():
        try:
            need = int(w.get("qty", 1)) - acquire.held(con, w["item"])
            if need > 0:
                out.append({"item": w["item"], "qty": need, "why": w.get("why", "upgrade")})
        except Exception:                                               # noqa: BLE001
            continue
    return out


def _way(con, g, p, w, live=False):
    from . import acquire
    try:
        return acquire.best_way(con, g, p, w["item"], w["qty"], None, can_build=True, live=live)
    except Exception:                                                   # noqa: BLE001
        return None


def candidates(con, g, p, best_known, hop_to):
    """-> [(rate, label, step text, note)]: a purchase step when THIS system is the cheapest way (buy beats build, detours counted) to get a wished item."""
    from . import acquire
    out = []
    wallet = float(getattr(p, "wallet_isk", 0.0) or 0.0)
    for w in wishes(con, p):
        way = _way(con, g, p, w)
        if not way or way["mode"] != "buy" or not way.get("buy") or way["buy"]["system"] != p.current_system:
            continue
        if way["buy"]["price"] * way["qty"] > wallet * MAX_SHARE:
            continue
        way = _way(con, g, p, w, live=True) or way                      # today's prices for the step you are about to act on
        if not way.get("buy") or way["mode"] != "buy" or way["buy"]["system"] != p.current_system:
            continue
        txt = acquire.first_action(con, g, p, way, hop_to)
        if not txt.startswith("STEP:"):
            continue
        note = f"{w['why']}: this is the cheapest place to buy it (cheaper than building it); the plan then uses what you own"
        out.append((max(best_known, 1.0) * RATE_EDGE, f"shopping: {w['item']}", txt, note))
        break                                                           # one purchase at a time
    return out


def lines(con, g, p):
    """-> text for the long view: every wish with its cheapest source."""
    ws = wishes(con, p)
    if not ws:
        return ""
    L = ["SHOPPING (bought where cheapest, when your route passes: every later step then uses what you own):"]
    for w in ws:
        way = _way(con, g, p, w)
        if not way or not way.get("buy"):
            L.append(f"   {w['qty']} x {w['item']} ({w['why']}): no price scanned yet (run  python -m eve_profit scan)")
            continue
        b = way["buy"]
        cheaper = ""
        if way.get("build") and way["mode"] == "buy":
            cheaper = f"; building would cost about {way['build']['cost']:,.0f}"
        elif way["mode"] == "build":
            cheaper = "; BUILDING is cheaper than buying"
        where = "HERE" if b["system"] == p.current_system else f"{b['system']} ({b['jumps']} jumps)"
        L.append(f"   {w['qty']} x {w['item']} ({w['why']}): ~{b['price'] * way['qty']:,.0f} ISK at {b['station'] or b['system']}, {where}{cheaper}")
    return "\n".join(L)
