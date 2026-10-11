"""Reprocess-or-sell: for an ore (or any item in reprocess.json) compare selling it raw with refining it and selling the minerals.
Refined = minerals sold at the best buy orders within reach (after sales tax, the reprocessing fee and the trip, minutes valued at your time)
versus the raw stack sold right here. Also prints the refining yield above which refining would win (train skills / better station)."""
import json
import os

from .orders import load_books, sell_into_bids

_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reprocess.json")
TIME_VALUE_HR = 600000.0
PER_JUMP_MIN = 3.0
REFINE_MIN = 3.0            # reprocess and collect
SELL_MIN = 2.0              # sell the minerals
RAW_MIN = 3.0               # sell the raw stack
MAX_JUMPS = 4
WIN_MARGIN = 1.10           # refining must beat raw by 10% (and 25,000 ISK) after time cost to be advised


def load():
    try:
        return json.load(open(_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def known(name):
    return (name or "").lower() in {k.lower() for k in load().get("ores", {})}


def refine_option(con, g, p, name, qty, raw_net):
    """-> dict for the refine route, or None when this item is not in reprocess.json / no mineral prices."""
    d = load()
    ore = next((v for k, v in d.get("ores", {}).items() if k.lower() == (name or "").lower()), None)
    if not ore or qty <= 0:
        return None
    minerals = {m: int(qty * per) for m, per in ore["per_unit"].items()}
    ids = {}
    for m in minerals:
        r = con.execute("SELECT type_id FROM types WHERE name=? COLLATE NOCASE", (m,)).fetchone()
        if not r:
            return None
        ids[m] = r[0]
    cur = g.id_of(p.current_system)
    reach = g.reach(cur, MAX_JUMPS, p.avoid_yellow)
    _, buys = load_books(con, set(reach))
    fee = d.get("fee_per_unit", 0.0) * qty
    best = None
    for s, route in reach.items():
        net = sum(sell_into_bids(buys.get(ids[m], {}).get(s, []), q, p.sales_tax)[1] for m, q in minerals.items())
        if net <= 0:
            continue
        minutes = REFINE_MIN + SELL_MIN + 2 * route.jumps * PER_JUMP_MIN
        score = net - fee - minutes / 60.0 * TIME_VALUE_HR
        if best is None or score > best["score"]:
            best = {"where": g.name[s], "jumps": route.jumps, "gross_net": net, "fee": fee, "net": net - fee, "minutes": minutes, "score": score}
    if not best:
        return None
    raw_score = raw_net - RAW_MIN / 60.0 * TIME_VALUE_HR
    best.update({"minerals": minerals, "raw_net": raw_net, "raw_score": raw_score, "yield_seen": d.get("yield_seen", 0.0)})
    # yield at which refining would match selling raw (the mineral value scales with yield; the fee and the minutes do not)
    cost_fixed = fee + best["minutes"] / 60.0 * TIME_VALUE_HR
    need = raw_score + cost_fixed
    best["breakeven_yield"] = (d.get("yield_seen", 0.0) * need / best["gross_net"]) if best["gross_net"] > 0 else None
    best["refine_wins"] = best["score"] > raw_score * WIN_MARGIN and best["net"] - raw_net > 25000
    return best


def describe(name, o):
    mins = " + ".join(f"{q:,} {m}" for m, q in o["minerals"].items())
    L = [f"      REFINE or SELL RAW? refining {name} at your {o['yield_seen'] * 100:.0f}% yield gives {mins}: ~{o['net']:,.0f} ISK after sales tax and the {o['fee']:,.0f} fee"
         f" if sold at {o['where']} ({o['jumps']} jumps, ~{o['minutes']:.0f} min) vs ~{o['raw_net']:,.0f} selling raw now."]
    if o["refine_wins"]:
        L.append("      => REFINE FIRST: it pays more even after the extra minutes (Reprocess in the station, then sell the minerals there).")
    else:
        be = o.get("breakeven_yield")
        L.append("      => SELL RAW." + (f" Refining only wins above about {be * 100:.0f}% yield (train Reprocessing skills / a better station)." if be else ""))
    return L
