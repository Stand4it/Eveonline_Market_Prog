"""Long-term COMBAT goal for `next --plan`: combat is blocked until a ship + fit passes the 99% win rule; the plan lists what to BUY to open it (hull, guns,
tank) with live market prices, so it is a standing purchase goal that joins the ranking by ISK/hr when the rest runs out."""
import json
import os

_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ship_fits.json")


def _cheapest(con, name):
    try:
        r = con.execute("SELECT MIN(o.price) FROM orders o JOIN types t ON t.type_id=o.type_id WHERE t.name=? COLLATE NOCASE AND o.is_buy=0", (name,)).fetchone()
        return r[0] if r and r[0] else None
    except Exception:                                                   # noqa: BLE001
        return None


def format_goal(con):
    try:
        d = json.load(open(_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    g = d.get("combat_goal")
    if not g:
        return ""
    lines = ["COMBAT (long-term goal, parked): " + g["status"], "   Why: " + g["why"]]
    total = 0.0
    for it in g.get("buy", []):
        pr = _cheapest(con, it["item"])
        total += (pr or 0) * it.get("qty", 1)
        lines.append(f"   BUY {it.get('qty', 1)} x {it['item']}  ({it['for']})  " + (f"~{pr:,.0f} ISK each (cheapest sell seen)" if pr else "price not scanned"))
    if total:
        lines.append(f"   Shopping list total about {total:,.0f} ISK. It joins the plan when your ISK/hr elsewhere flattens out and the fit passes the 99% win rule.")
    lines.append("   Opens: Soldier of Fortune kill goals (Frigate 14/75, Cruiser 0/75, Destroyer 0/75), Homefront raids, Crimson Harvest (to 11-03), bounties/missions.")
    return "\n".join(lines)
