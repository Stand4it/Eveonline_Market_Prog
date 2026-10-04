"""Mining: fill hold, fly to best-paying buy order, sell. Time includes mining."""
from .opportunity import Opportunity
from .orders import load_books, sell_into_bids
from .risk import route_risk


def find_mining(con, g, p):
    if p.mining_yield_m3_s <= 0 or not p.minable_ores:
        return []
    cur = g.id_of(p.current_system)
    reach = g.reach(cur, p.max_jumps, p.avoid_yellow)
    _, buys = load_books(con, reach)
    out = []
    for name in p.minable_ores:
        row = con.execute("SELECT type_id,volume FROM types WHERE name=? COLLATE NOCASE",
                          (name,)).fetchone()
        if not row or row["volume"] <= 0:
            continue
        units = int(p.mining_hold // row["volume"])
        mine_s = units * row["volume"] / p.mining_yield_m3_s
        for b, bids in buys[row["type_id"]].items():
            sold, net = sell_into_bids(bids, units, p.sales_tax)
            if sold == 0:
                continue
            rt = reach[b]
            loss, wait = route_risk(g, rt.path, p.ship_value_isk + net)
            secs = (mine_s + 2 * rt.jumps * p.jump_seconds + p.dock_overhead_s
                    + p.trade_overhead_s + 2 * wait)
            out.append(Opportunity(
                "mine",
                f"Mine {sold:,} x {name} ({mine_s / 60:.0f} min), sell @ {g.name[b]}",
                net, loss, 2 * rt.jumps, secs / 3600, " > ".join(g.name[s] for s in rt.path),
                {"type_id": row["type_id"], "units": sold, "mine_minutes": mine_s / 60}))
    return out
