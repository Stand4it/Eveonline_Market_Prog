"""Mining: fill hold, fly to best-paying buy order, sell. Time includes mining."""
from .opportunity import Opportunity
from .orders import load_books, sell_into_bids
from .risk import route_risk
from .skills import have, type_missing


def accepted_jobs(con):
    """Ores of the freelance mining jobs you accepted (kept in the database, so the repo file never conflicts with `git pull`)."""
    import json
    try:
        r = con.execute("SELECT value FROM meta WHERE key='jobs_accepted'").fetchone()
        return set(json.loads(r[0])) if r else set()
    except Exception:                                                   # noqa: BLE001
        return set()


def freelance_bonus(ore, con=None):
    """(ISK per unit, remaining unit cap) a freelance 'Mine Materials' job you ACCEPTED pays for this ore on top of selling it (freelance_jobs.json)."""
    import json
    import os
    try:
        acc = accepted_jobs(con) if con is not None else set()
        f = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "freelance_jobs.json")
        for j in json.load(open(f, encoding="utf-8")).get("mining_jobs", []):
            if j["ore"] in acc and j["ore"].lower() == str(ore).lower():
                return float(j["isk_per_unit"]), max(0, int(j["cap_units"]) - int(j.get("mined_so_far", 0)))
    except (OSError, ValueError, KeyError):
        pass
    return 0.0, 0


def find_mining(con, g, p):
    if p.mining_yield_m3_s <= 0 or not p.minable_ores:
        return []
    cur = g.id_of(p.current_system)
    reach = g.reach(cur, p.max_jumps, p.avoid_yellow)
    _, buys = load_books(con, reach)
    skills = have(con)
    out = []
    for name in p.minable_ores:
        row = con.execute("SELECT type_id,volume FROM types WHERE name=? COLLATE NOCASE",
                          (name,)).fetchone()
        if not row or row["volume"] <= 0:
            continue
        if skills and type_missing(con, row["type_id"], skills):
            continue                  # ore needs a skill you lack
        units = int(p.mining_hold // row["volume"])
        mine_s = units * row["volume"] / p.mining_yield_m3_s
        for b, bids in buys[row["type_id"]].items():
            sold, net = sell_into_bids(bids, units, p.sales_tax)
            if sold == 0:
                continue
            fb, cap = freelance_bonus(name, con)
            net += fb * min(units, cap)                               # an accepted freelance job pays per unit mined on top of the sale
            rt = reach[b]
            loss, wait = route_risk(g, rt.path, p.ship_value_isk + net)
            secs = (mine_s + 2 * rt.jumps * p.jump_seconds + p.dock_overhead_s
                    + p.trade_overhead_s + 2 * wait)
            out.append(Opportunity(
                "mine",
                f"Mine {sold:,} x {name} ({mine_s / 60:.0f} min), sell @ {g.name[b]}",
                net, loss, 2 * rt.jumps, secs / 3600, " > ".join(g.name[s] for s in rt.path),
                {"type_id": row["type_id"], "units": sold, "mine_minutes": mine_s / 60},
                waypoints=rt.path[1:]))
    return out


def accept_job(ore, con=None):
    """`done` / `done --goal "job veldspar"`: you pressed Accept on that freelance mining job. -> message."""
    import json
    import os
    f = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "freelance_jobs.json")
    d = json.load(open(f, encoding="utf-8"))
    hit = [j for j in d.get("mining_jobs", []) if j["ore"].lower() == ore.lower()]
    if not hit:
        return "No such freelance mining job recorded: " + ", ".join(j["ore"] for j in d.get("mining_jobs", []))
    if con is not None:
        acc = accepted_jobs(con) | {hit[0]["ore"]}
        con.execute("INSERT OR REPLACE INTO meta VALUES('jobs_accepted',?)", (json.dumps(sorted(acc)),))
        con.commit()
    return f"OK, the {hit[0]['ore']} job pays {hit[0]['isk_per_unit']:.2f} ISK per unit mined on top of the ore sale; mining plans now count it. Run  python -m eve_profit next"
