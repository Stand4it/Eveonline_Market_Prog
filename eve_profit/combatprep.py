"""Getting a combat-ready ship, ONE concrete step at a time. A 'test a combat mission' turn is only valid when the ship you fly is a combat hull with guns, ammo and a
tank; until then the step is the first missing piece: board the right hull, fit the turrets you own (fetching them where they lie), buy ammo / the armor repairer where
that is cheapest, show the fitting window, and only then go to a security agent. The kit comes from ship_fits.json `combat_kit`."""
import json
import os

_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ship_fits.json")
DEFAULT_KIT = {"hulls": ["Incursus", "Tristan", "Atron", "Maulus"], "turret_words": ["railgun", "blaster", "autocannon", "artillery", "laser", "pulse"],
               "turrets": 2, "turret_buy": "150mm Carbide Railgun I", "ammo": "Antimatter Charge S", "ammo_qty": 200,
               "tank_words": ["armor repairer", "shield booster"], "tank_buy": "Small Armor Repairer I"}


def kit():
    try:
        return {**DEFAULT_KIT, **json.load(open(_FILE, encoding="utf-8")).get("combat_kit", {})}
    except (OSError, ValueError):
        return dict(DEFAULT_KIT)


def _q(con, sql, args=()):
    try:
        return con.execute(sql, args).fetchall()
    except Exception:                                                   # noqa: BLE001
        return []


def _meta(con, key):
    r = _q(con, "SELECT value FROM meta WHERE key=?", (key,))
    try:
        return json.loads(r[0][0]) if r else {}
    except ValueError:
        return {}


def state(con, p):
    """What the ship you fly has: hull name, fitted turrets / tank (slot modules), cargo (by name), plus every item you own by place."""
    hull = (_q(con, "SELECT name FROM types WHERE type_id=?", (p.ship_type_id,)) or [[""]])[0][0] or p.ship_name
    fitted = [(r[0] or "", int(r[1] or 1)) for r in _q(con, "SELECT t.name, f.quantity FROM fitted f JOIN types t ON t.type_id=f.type_id WHERE f.flag LIKE '%Slot%'")]
    names = {r[0]: r[1] for r in _q(con, "SELECT type_id,name FROM types")}
    cargo = {names.get(int(t), str(t)): int(q) for t, q in _meta(con, "cargo_now").items()}
    stock = {}
    for tid, sid, q in _q(con, "SELECT type_id,system_id,quantity FROM inventory"):
        stock.setdefault(names.get(tid, str(tid)), []).append((sid, int(q)))
    ships = [(r[0], r[1]) for r in _q(con, "SELECT t.name, m.system_id FROM my_ships m JOIN types t ON t.type_id=m.type_id")]
    return {"hull": hull, "fitted": fitted, "cargo": cargo, "stock": stock, "ships": ships}


def _holder(g, p, stock_rows):
    """Nearest system (by jumps) that holds some of this item: (system name, jumps, qty) or None."""
    best = None
    try:
        cur = g.id_of(p.current_system)
        reach = g.reach(cur, 40, p.avoid_yellow)
    except Exception:                                                   # noqa: BLE001
        return None
    for sid, q in stock_rows:
        if sid in reach and (best is None or reach[sid].jumps < best[1]):
            best = (g.name[sid], reach[sid].jumps, q)
    return best


def next_step(con, g, p, hop_to):
    """-> step text for the FIRST missing piece of a combat-ready ship, or '' when the ship is ready. hop_to(system, why, lines) gives the next-jump step."""
    k = kit()
    s = state(con, p)
    here = p.current_system
    # 1. a combat hull
    if not any(h.lower() in s["hull"].lower() for h in k["hulls"]):
        for name, sid in s["ships"]:
            if any(h.lower() in name.lower() for h in k["hulls"]):
                sysname = g.name[sid]
                if sysname == here:
                    return (f"STEP: BOARD your {name} (combat hull)\n   DO ONLY THIS: in the station window open the Hangars tab > Ship Hangar > right-click your {name} > Board Ship.\n"
                            f"   LATER: fit guns, ammo and tank; you fly a {s['hull']} now, which is not a combat ship")
                return hop_to(sysname, f"your {name} is there: board it, then fit guns, ammo and tank", [])
        return ("STEP: BUY a combat frigate\n   DO ONLY THIS: " + f"Market > {k['hulls'][0]} > buy one at the cheapest station near you (about 100,000 ISK); see `next --plan` for the sources.")
    # 2. turrets
    turrets_fitted = sum(q for n, q in s["fitted"] if any(w in n.lower() for w in k["turret_words"]))
    if turrets_fitted < k["turrets"]:
        need = k["turrets"] - turrets_fitted
        for name, rows in s["stock"].items():
            if any(w in name.lower() for w in k["turret_words"]) and "civilian" not in name.lower():
                h = _holder(g, p, rows)
                if not h:
                    continue
                if h[0] == here:
                    n = min(need, h[2])
                    return (f"STEP: FIT {n} x {name} to your {s['hull']}\n   DO ONLY THIS: open the fitting window (Alt+F) and drag {n} x {name} from the hangar/cargo into the high slots (turret icons).\n"
                            f"   LATER: ammo, tank, then show me the fitting window")
                return hop_to(h[0], f"{name} is there ({h[2]} units): fit them to your {s['hull']}", [])
        try:
            from .acquire import best_way, first_action
            w = best_way(con, g, p, k["turret_buy"], need, None, can_build=False, live=True)
            t = first_action(con, g, p, w, hop_to) if w else ""
            if t:
                return t
        except Exception:                                               # noqa: BLE001
            pass
        return f"STEP: BUY {need} x {k['turret_buy']}\n   DO ONLY THIS: Market > {k['turret_buy']} > buy {need} at the cheapest station near you."
    # 3. ammo in the hold
    have_ammo = s["cargo"].get(k["ammo"], 0)
    if have_ammo < k["ammo_qty"]:
        rows = s["stock"].get(k["ammo"], [])
        h = _holder(g, p, rows) if rows else None
        if h and h[0] == here:
            return (f"STEP: LOAD {k['ammo_qty']} x {k['ammo']} into your {s['hull']}'s cargo\n   DO ONLY THIS: drag {k['ammo']} from the hangar into the ship's cargo (and into the guns when fitted).\n"
                    f"   LATER: tank, then show me the fitting window")
        if h:
            return hop_to(h[0], f"{k['ammo']} is there", [])
        try:
            from .acquire import best_way, first_action
            w = best_way(con, g, p, k["ammo"], k["ammo_qty"] - have_ammo, None, can_build=False, live=True)
            t = first_action(con, g, p, w, hop_to) if w else ""
            if t:
                return t
        except Exception:                                               # noqa: BLE001
            pass
        return f"STEP: BUY {k['ammo_qty']} x {k['ammo']}\n   DO ONLY THIS: Market > {k['ammo']} > buy {k['ammo_qty']} at the cheapest station near you."
    # 4. tank
    if not any(any(w in n.lower() for w in k["tank_words"]) for n, _ in s["fitted"]):
        rows = s["stock"].get(k["tank_buy"], [])
        h = _holder(g, p, rows) if rows else None
        if h and h[0] == here:
            return f"STEP: FIT 1 x {k['tank_buy']} to your {s['hull']}\n   DO ONLY THIS: fitting window (Alt+F): drag the {k['tank_buy']} into a low slot (armor repairer = low).\n   LATER: show me the fitting window"
        if h:
            return hop_to(h[0], f"{k['tank_buy']} is there", [])
        try:
            from .acquire import best_way, first_action
            w = best_way(con, g, p, k["tank_buy"], 1, None, can_build=False, live=True)
            t = first_action(con, g, p, w, hop_to) if w else ""
            if t:
                return t
        except Exception:                                               # noqa: BLE001
            pass
        return f"STEP: BUY 1 x {k['tank_buy']}\n   DO ONLY THIS: Market > {k['tank_buy']} > buy 1 at the cheapest station near you."
    # 5. numbers for the model
    if not _meta(con, "combat_fit_seen").get(s["hull"]):
        return (f"STEP: SHOW ME the fitting window of your {s['hull']} (about 30 seconds)\n   DO ONLY THIS: open the Fitting window (Alt+F) with the guns, ammo and repairer fitted, click Simulate if offered.\n"
                "   Show me: dps (Offense), EHP (Defense), capacitor, speed: the win-chance rule needs them.\n   To send it: press  Win + Shift + S , drag a box around the window, then press  Ctrl + V  in the chat with me.")
    return ""


def mark_fit_seen(con, hull):
    import json as _j
    st = _meta(con, "combat_fit_seen")
    st[hull] = 1
    con.execute("INSERT OR REPLACE INTO meta VALUES('combat_fit_seen', ?)", (_j.dumps(st),))
    con.commit()


def agent_step(g, p, hop_to):
    """The kit is ready: go to the nearest known Security agent (mission_agents.json) and take a mission. -> step text."""
    try:
        d = json.load(open(os.path.join(os.path.dirname(_FILE), "mission_agents.json"), encoding="utf-8"))
        cur = g.id_of(p.current_system)
        reach = g.reach(cur, 40, p.avoid_yellow)
        best = None
        for a in d.get("agents", []):
            if a.get("type") != "Security":
                continue
            try:
                sid = g.id_of(a["system"])
            except Exception:                                           # noqa: BLE001
                continue
            if sid in reach and (best is None or reach[sid].jumps < best[0]):
                best = (reach[sid].jumps, a)
        if best:
            j, a = best
            if a["system"] == p.current_system:
                return (f"STEP: ACCEPT a Level {a['level']} security mission from {a['name']} ({a['corp']})\n   DO ONLY THIS: station window > Agents tab > {a['name']} > Start Conversation > read it > Accept.\n"
                        f"   LATER: fly the mission in your combat frigate; time it (combat only if the win chance is above 99%: show me the fitting numbers first)")
            return hop_to(a["system"], f"{a['name']} ({a['corp']}, level {a['level']} security) is there: accept a mission", [])
    except Exception:                                                   # noqa: BLE001
        pass
    return ""
