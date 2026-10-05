"""Combat (NPC) and salvage opportunities.
SAFETY RULES (built in): only NPC targets and your OWN wrecks. No ganking, no taking
other players' wrecks/cans. Never routes through red; hot (recent-kill) systems skipped.
ISK/hour figures are PLACEHOLDERS (no public API for payouts): log real runs with
`python -m eve_profit log --activity NAME --isk X --hours Y` and they replace the guess."""
from .opportunity import Opportunity
from .orders import load_books
from .risk import route_risk

CALIBRATE_AFTER = 3

# name, kind, min_sec, max_sec, isk/h, wrecks/h, base p_loss/h (non-NPC causes), min_dps, session_h,
# enemy_ehp (per wave), threat_dps (per wave, incl. spikes), waves/h   -- ALL placeholders
DEFAULT_ACTIVITIES = [
    ("High-sec belt ratting (frigate)", "combat", 0.5, 1.0, 4_000_000, 40, 0.0005, 60, 1.0, 3_000, 40, 6),
    ("Level 2 security mission", "combat", 0.5, 1.0, 10_000_000, 25, 0.0003, 150, 1.0, 15_000, 60, 4),
    ("Level 3 security mission", "combat", 0.5, 1.0, 25_000_000, 40, 0.0005, 300, 1.0, 60_000, 250, 4),
    ("Level 4 security mission", "combat", 0.5, 1.0, 60_000_000, 60, 0.001, 600, 1.0, 250_000, 700, 3),
]
# type name, avg units per wreck, chance (guesses; refine from your salvage results)
DEFAULT_SALVAGE = [("Tripped Power Circuit", 0.4, 1.0), ("Charred Micro Circuit", 0.4, 1.0),
                   ("Conductive Polymer", 0.3, 1.0), ("Burned Logic Circuit", 0.3, 1.0),
                   ("Armor Plates", 0.3, 1.0), ("Smashed Trigger Unit", 0.2, 1.0)]


def seed_defaults(con):
    con.executemany("INSERT OR IGNORE INTO activities(name,kind,min_sec,max_sec,isk_per_hour,"
                    "wrecks_per_hour,p_loss_per_hour,min_dps,session_hours,enemy_ehp,threat_dps,"
                    "waves_per_hour) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", DEFAULT_ACTIVITIES)
    con.executemany("UPDATE activities SET enemy_ehp=?,threat_dps=?,waves_per_hour=? "
                    "WHERE name=? AND enemy_ehp=0 AND threat_dps=0",   # fill migrated rows only
                    [(d[9], d[10], d[11], d[0]) for d in DEFAULT_ACTIVITIES])
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


def win_assessment(a, p):
    """-> (margin, p_lose_session). margin = ship_ehp / damage you expect to take per wave.
    Time to kill a wave = enemy_ehp / your DPS; damage = (threat - sustained tank) * that time."""
    ttk = a["enemy_ehp"] / p.combat_dps
    dmg = max(0.0, a["threat_dps"] - p.ship_tank_dps) * ttk
    margin = float("inf") if dmg <= 0 else p.ship_ehp / dmg
    p_wave = 0.0 if margin == float("inf") else 1 / (1 + margin ** 4)   # 3x->1.2%, 5x->0.16%, 1x->50%
    waves = max(1.0, a["waves_per_hour"] * a["session_hours"])
    p_session = 1 - (1 - p_wave) ** waves
    return margin, min(1.0, p_session + a["p_loss_per_hour"] * a["session_hours"])


def replacement_cost(con, p, reach, sells):
    """ISK to be flying again: cheapest of buying the hull in range or building it from a
    blueprint you own (materials at cheapest asks), plus fit, minus insurance."""
    from .manufacturing import buy_cost, material_qty
    hull = None
    if p.ship_type_id:
        asks = [a[0][0] for s_, a in sells.get(p.ship_type_id, {}).items() if s_ in reach]
        hull = min(asks) if asks else None
        bp = con.execute("SELECT m.blueprint_id,m.me FROM my_blueprints m JOIN bp_products b "
                         "ON b.blueprint_id=m.blueprint_id WHERE b.product_id=?",
                         (p.ship_type_id,)).fetchone()
        if bp:
            total = 0.0
            for m in con.execute("SELECT material_id,quantity FROM bp_materials "
                                 "WHERE blueprint_id=?", (bp["blueprint_id"],)):
                q = material_qty(m["quantity"], 1, bp["me"])
                costs = [c for c in (buy_cost(a, q) for s_, a in sells.get(m["material_id"], {}).items()
                                     if s_ in reach) if c is not None]
                if not costs:
                    total = None
                    break
                total += min(costs)
            if total is not None and (hull is None or total < hull):
                hull = total
    if hull is None:
        return max(0.0, p.ship_value_isk - p.insurance_payout_isk)
    return max(0.0, hull + p.fit_value_isk - p.insurance_payout_isk)


def find_combat(con, g, p):
    if p.combat_dps <= 0 or p.ship_ehp <= 0:
        return []        # can't judge win odds without your DPS and ship EHP -> recommend nothing
    cur = g.id_of(p.current_system)
    reach = g.reach(cur, p.max_jumps, p.avoid_yellow)
    sells, buys = load_books(con, reach)
    repl = replacement_cost(con, p, reach, sells)
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
        margin, p_lose = win_assessment(a, p)
        session_profit = rate * a["session_hours"]
        safe = margin >= p.min_win_margin
        affordable = margin >= p.risky_win_margin and session_profit >= repl
        if not (safe or affordable):
            continue     # not likely enough to win and one session wouldn't repay the ship
        rt = reach[s]
        loss_travel, wait = route_risk(g, rt.path, p.ship_value_isk)
        risk = 2 * loss_travel + p_lose * repl      # expected cost of losing the ship
        travel_h = (2 * rt.jumps * p.jump_seconds + 2 * wait + p.dock_overhead_s) / 3600
        tag = (" (your avg)" if learned else " (estimate)") + f" win {100 * (1 - p_lose):.1f}%"
        base = Opportunity("combat", f"{a['name']} @ {g.name[s]}{tag}",
                           rate * a["session_hours"], risk, 2 * rt.jumps,
                           a["session_hours"] + travel_h, " > ".join(g.name[x] for x in rt.path),
                           {"activity": a["name"], "learned": learned, "margin": margin, "p_lose": p_lose,
                            "replacement_isk": repl},
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
