"""Combat (NPC) and salvage opportunities.
SAFETY RULES (built in): only NPC targets and your OWN wrecks. No ganking, no taking
other players' wrecks/cans. Never routes through red; hot (recent-kill) systems skipped.
ISK/hour figures are PLACEHOLDERS (no public API for payouts): log real runs with
`python -m eve_profit log --activity NAME --isk X --hours Y` and they replace the guess."""
from .opportunity import Opportunity
from .orders import load_books
from .risk import route_risk

CALIBRATE_AFTER = 3

# name, kind, min_sec, max_sec, isk/h, wrecks/h, p_loss/h, min_dps, session_h
DEFAULT_ACTIVITIES = [
    ("High-sec belt ratting (frigate)", "combat", 0.5, 1.0, 4_000_000, 40, 0.0005, 60, 1.0),
    ("Level 2 security mission", "combat", 0.5, 1.0, 10_000_000, 25, 0.0003, 150, 1.0),
    ("Level 3 security mission", "combat", 0.5, 1.0, 25_000_000, 40, 0.0005, 300, 1.0),
    ("Level 4 security mission", "combat", 0.5, 1.0, 60_000_000, 60, 0.001, 600, 1.0),
]
# type name, avg units per wreck, chance (guesses; refine from your salvage results)
DEFAULT_SALVAGE = [("Tripped Power Circuit", 0.4, 1.0), ("Charred Micro Circuit", 0.4, 1.0),
                   ("Conductive Polymer", 0.3, 1.0), ("Burned Logic Circuit", 0.3, 1.0),
                   ("Armor Plates", 0.3, 1.0), ("Smashed Trigger Unit", 0.2, 1.0)]


def seed_defaults(con):
    con.executemany("INSERT OR IGNORE INTO activities VALUES(?,?,?,?,?,?,?,?,?)",
                    DEFAULT_ACTIVITIES)
    con.executemany("INSERT OR IGNORE INTO salvage_items VALUES(?,?,?)", DEFAULT_SALVAGE)
    con.commit()


def calibrated_rate(con, name, guess):
    r = con.execute("SELECT COUNT(*), SUM(isk), SUM(hours) FROM activity_log WHERE activity=?",
                    (name,)).fetchone()
    if r[0] >= CALIBRATE_AFTER and r[2] > 0:
        return r[1] / r[2], True
    return guess, False


def salvage_value_per_wreck(con, buys, reach, tax):
    """Market value of average salvage from one wreck (best bid in reach, after tax)."""
    total = 0.0
    for row in con.execute("SELECT s.qty_per_wreck,s.chance,t.type_id FROM salvage_items s "
                           "JOIN types t ON t.name=s.type_name COLLATE NOCASE"):
        bids = [b[0][0] for sysid, b in buys.get(row["type_id"], {}).items() if sysid in reach]
        if bids:
            total += row["qty_per_wreck"] * row["chance"] * max(bids) * (1 - tax)
    return total


def find_combat(con, g, p):
    if p.combat_dps <= 0:
        return []
    cur = g.id_of(p.current_system)
    reach = g.reach(cur, p.max_jumps, p.avoid_yellow)
    _, buys = load_books(con, reach)
    per_wreck = salvage_value_per_wreck(con, buys, reach, p.sales_tax) if p.can_salvage else 0
    out = []
    for a in con.execute("SELECT * FROM activities").fetchall():
        if p.combat_dps < a["min_dps"]:
            continue
        cands = [s for s in reach if a["min_sec"] <= g.sec[s] <= a["max_sec"]
                 and not g.is_hot(s) and (not p.avoid_yellow or not g.is_yellow(s))]
        if not cands:
            continue
        s = min(cands, key=lambda x: reach[x].cost)
        rate, learned = calibrated_rate(con, a["name"], a["isk_per_hour"])
        rt = reach[s]
        loss_travel, wait = route_risk(g, rt.path, p.ship_value_isk)
        risk = 2 * loss_travel + a["p_loss_per_hour"] * a["session_hours"] * p.ship_value_isk
        travel_h = (2 * rt.jumps * p.jump_seconds + 2 * wait + p.dock_overhead_s) / 3600
        tag = " (your avg)" if learned else " (estimate)"
        base = Opportunity("combat", f"{a['name']} @ {g.name[s]}{tag}",
                           rate * a["session_hours"], risk, 2 * rt.jumps,
                           a["session_hours"] + travel_h, " > ".join(g.name[x] for x in rt.path),
                           {"activity": a["name"], "learned": learned},
                           rt.path[1:])
        out.append(base)
        if p.can_salvage and per_wreck > 0 and a["wrecks_per_hour"] > 0:
            wrecks = a["wrecks_per_hour"] * a["session_hours"]
            extra_h = wrecks * p.salvage_wreck_seconds / 3600
            out.append(Opportunity(
                "combat+salv", f"{a['name']} + salvage own wrecks @ {g.name[s]}{tag}",
                base.profit_isk + wrecks * per_wreck, risk, base.jumps,
                base.hours + extra_h, base.route,
                {"activity": a["name"], "wrecks": wrecks, "salvage_per_wreck": per_wreck},
                base.waypoints))
    return out
