"""Where to mine (mining_sites.json, read from Agency > Resource Harvesting): ranks the known sites by what their best ore sells for per m3
in the scanned markets, minus a small penalty per jump away. Used by the freelance-mining test in `next`."""
import json
import os

_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mining_sites.json")
JUMP_PENALTY = 0.03        # each jump away costs 3% of the site's value (round-trip time and risk)


def sites():
    try:
        return json.load(open(_FILE, encoding="utf-8")).get("sites", [])
    except (OSError, ValueError):
        return []


def ore_price_per_m3(con, name):
    """Best buy-order price (instant sale) per m3 for an ore item name; None if unknown."""
    try:
        r = con.execute("SELECT t.volume, MAX(o.price) FROM types t JOIN orders o ON o.type_id=t.type_id AND o.is_buy=1 "
                        "WHERE t.name=? COLLATE NOCASE", (name,)).fetchone()
    except Exception:                                                   # noqa: BLE001
        return None
    return (r[1] / r[0]) if r and r[0] and r[1] else None


def rank_sites(con, max_sec_floor=0.5):
    out = []
    for s in sites():
        if s["kind"] == "ice" or s["sec"] < max_sec_floor or not s["ores"]:
            continue
        prices = [(ore_price_per_m3(con, o), o) for o in s["ores"]]
        prices = [(pr, o) for pr, o in prices if pr]
        best = max(prices) if prices else (None, None)
        score = (best[0] or 0.0) * (1 - JUMP_PENALTY * s["jumps"])
        out.append({**s, "best_ore": best[1], "per_m3": best[0], "score": score})
    out.sort(key=lambda x: -x["score"])
    return out


def recommend(con):
    r = rank_sites(con)
    if not r:
        return ""
    top = r[0]
    line = (f"   WHERE: {top['system']} ({top['jumps']} jumps, {top['belts']} belts, {top['sec']}): best ore {top['best_ore']} ~{top['per_m3']:,.0f} ISK/m3"
            if top["per_m3"] else f"   WHERE: {top['system']} ({top['jumps']} jumps, {top['belts']} belts); ore prices not scanned yet")
    alt = [f"{x['system']} {x['jumps']}j" for x in r[1:3]]
    return line + (f"   (next best: {', '.join(alt)})" if alt else "")
