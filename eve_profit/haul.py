"""Hauling candidate for `next`: stock lying here that sells much better at another scanned market. Scored in ISK per hour like every
other activity: (extra ISK vs selling it right here) / (trips x round trip + docking). Ore may ride in a mining ship's ore hold."""
import math

from .orders import load_books, sell_into_bids
from .sellplan import is_ore, ore_hold_m3

DOCK_MIN = 2.0
MIN_GAIN = 50_000.0
MAX_JUMPS = 25
MAX_TRIPS = 3


def haul_option(con, g, p):
    """Best destination for the stock lying in your current system. -> dict or None."""
    cur = g.id_of(p.current_system)
    reach = g.reach(cur, MAX_JUMPS, p.avoid_yellow)
    _, buys = load_books(con, set(reach))
    vol = {r[0]: r[1] for r in con.execute("SELECT type_id,volume FROM types")}
    name = {r[0]: r[1] for r in con.execute("SELECT type_id,name FROM types")}
    ore_cap, cargo = ore_hold_m3(con), max(p.cargo_m3, 1.0)
    per_dest = {}
    for inv in con.execute("SELECT type_id,quantity FROM inventory WHERE system_id=?", (cur,)).fetchall():
        tid, qty = inv["type_id"], inv["quantity"]
        _, local = sell_into_bids(buys.get(tid, {}).get(cur, []), qty, p.sales_tax)
        best = None
        for b, bids in buys.get(tid, {}).items():
            if b == cur:
                continue
            sold, net = sell_into_bids(bids, qty, p.sales_tax)
            if sold and (best is None or net > best[1]):
                best = (b, net, sold)
        if not best or best[1] - local < 10_000:
            continue
        b, net, sold = best
        m3 = sold * (vol.get(tid, 0) or 0.0001)
        d = per_dest.setdefault(b, {"gain": 0.0, "net": 0.0, "ore_m3": 0.0, "other_m3": 0.0, "items": []})
        d["gain"] += net - local
        d["net"] += net
        d["ore_m3" if is_ore(name.get(tid, "")) and ore_cap else "other_m3"] += m3
        d["items"].append((name.get(tid, tid), sold, net, local))
    out = None
    for b, d in per_dest.items():
        trips = max(math.ceil(d["ore_m3"] / ore_cap) if d["ore_m3"] else 0, math.ceil(d["other_m3"] / cargo) if d["other_m3"] else 0, 1)
        if trips > MAX_TRIPS:
            continue
        j = reach[b].jumps
        minutes = trips * (2 * j * p.jump_seconds / 60.0 + 2 * DOCK_MIN)
        gain = d["gain"]
        if gain < MIN_GAIN or minutes <= 0:
            continue
        cand = {"dest": g.name[b], "jumps": j, "trips": trips, "minutes": minutes, "gain": gain, "rate_hr": gain * 60.0 / minutes,
                "items": sorted(d["items"], key=lambda x: -x[2]), "net": d["net"], "ore": bool(d["ore_m3"]), "ore_cap": ore_cap}
        if out is None or cand["rate_hr"] > out["rate_hr"]:
            out = cand
    return out


def haul_step(h):
    L = [f"STEP: HAUL your stock to {h['dest']} ({h['jumps']} jumps each way)"]
    for n, q, net, local in h["items"][:6]:
        L.append(f"   {q:>9,} x {n:<32} {net:>12,.0f} there vs {local:>10,.0f} here")
    L.append(f"   {h['trips']} trip(s), about {h['minutes']:.0f} min, +{h['gain']:,.0f} ISK more than selling here = {h['rate_hr']:,.0f} ISK/hr"
             + ("   (ore rides in your mining ship's ore hold)" if h["ore"] else ""))
    return "\n".join(L)
