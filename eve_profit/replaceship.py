"""In a CAPSULE (ship lost, owner 2026-10-22): the first step is a replacement ship, bought where it is cheapest counting your time.
Candidates (all flyable with Caldari Frigate/Destroyer basics): Catalyst (hauls 450 m3 + guns), Venture (mining frigate, ore hold), Corax (missile
destroyer). The pick = the hull whose hourly plan pays most minus its cost spread over 10 hours of use. A hull you own nearby is boarded instead."""
import time

from .health import record as _hrec

HULLS = [  # name, what it is for, ISK/hr it unlocks (a guess until timed: trading/courier, mining, combat L1)
    ("Catalyst", "trading, couriers (450 m3) and light combat", 1.00),
    ("Venture", "mining missions + daily ore goal (ore hold)", 0.60),
]
USE_HOURS = 10.0
MIN_PER_JUMP = 2.5


def in_capsule(p):
    return (p.ship_name or "").lower().startswith(("capsule", "pod")) or not (p.ship_name or "")


def candidate(con, g, p, best_known):
    """-> (rate, label, text, note) or None (not in a capsule / nothing for sale nearby)."""
    if not in_capsule(p):
        return None
    try:
        here = g.id_of(p.current_system)
        reach = g.reach(here, 10, p.avoid_yellow)
        rate = max(best_known, 1_000_000.0)
        per_jump = MIN_PER_JUMP * rate / 60.0
        best = None
        for hull, why, share in HULLS:
            for price, sid, loc in con.execute("SELECT o.price, o.system_id, o.location_id FROM orders o JOIN types t ON t.type_id=o.type_id "
                                               "WHERE t.name=? AND o.is_buy=0 AND o.volume_remain>0 AND o.fetched_at>?", (hull, time.time() - 2 * 86400)):
                if sid not in reach:
                    continue
                cost = price + reach[sid].jumps * per_jump              # one way: you fly the new ship on from there
                value = share * rate - cost / USE_HOURS                  # ISK/hr it lets you earn, minus its price spread over its use
                if best is None or value > best[0]:
                    best = (value, hull, why, price, sid, loc, reach[sid].jumps)
        if not best:
            return None
        _, hull, why, price, sid, loc, jumps = best
        st = con.execute("SELECT name FROM stations WHERE station_id=?", (loc,)).fetchone()
        where = st[0] if st else g.name[sid]
        if jumps:
            r = g.route(here, sid, 60, p.avoid_yellow)
            hop = g.name[r.path[1]] if r and len(r.path) > 1 else g.name[sid]
            text = (f"STEP: FLY to {hop} (in your capsule)\n"
                    f"   WHY: to buy a replacement {hull} in {g.name[sid]} ({jumps} jumps, ~{price:,.0f} ISK at {where}): {why}\n"
                    f"   DO ONLY THIS: fly to {hop} and stop there. Then run  python -m eve_profit next")
        else:
            text = (f"STEP: BUY A REPLACEMENT SHIP: 1 x {hull} here (~{price:,.0f} ISK)\n"
                    f"   WHY: you are in a capsule; the {hull} is for {why}.\n"
                    f"   DO ONLY THIS: Market > search '{hull}' > Buy 1 at {where}; then hangar > right-click it > Board Ship.\n"
                    f"   Then fit it: run  python -m eve_profit next  (it lists the modules to buy, cheapest first).\n"
                    f"   CHECK (every market that sells cheaper, priced with your time):  python scripts/where_buy.py \"{hull}\" 1")
        return 1e11, f"replacement ship: {hull}", text, "you are in a capsule: nothing else works without a ship"
    except Exception as _he:                                            # noqa: BLE001
        _hrec('replaceship', _he)
        return None
