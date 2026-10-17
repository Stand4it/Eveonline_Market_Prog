"""LEADS: opportunities SEEN on the map (a directional scan, a screenshot) that sit in one system for a limited time, e.g. a pile of wrecks to salvage.
A lead competes on the one plan list like everything else. Its ISK/hr is YOUR measured rate for that activity when there is one (average of the timed runs);
with no timed run it is an UNKNOWN and is modeled equal to the best ISK/hr on the list until real runs replace it. Travel (and fetching the ship that can do it)
is charged, and a lead that would expire before you get there is dropped. Data: leads.json."""
import json
import os
import time

_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "leads.json")
SWAP_MIN = 4.0
JUMP_MIN = 3.0


def load():
    try:
        return json.load(open(_FILE, encoding="utf-8")).get("leads", [])
    except (OSError, ValueError):
        return []


def _ship_system(con, g, p, word):
    """(ship name, system name) of a parked ship whose name contains `word`, or None."""
    try:
        for r in con.execute("SELECT t.name, m.system_id FROM my_ships m JOIN types t ON t.type_id=m.type_id"):
            if word.lower() in (r[0] or "").lower():
                return r[0], g.name[r[1]]
    except Exception:                                                   # noqa: BLE001
        pass
    return None


def _jumps(g, p, a, b):
    try:
        r = g.route(g.id_of(a), g.id_of(b), 60, p.avoid_yellow)
        return r.jumps if r else None
    except Exception:                                                   # noqa: BLE001
        return None


def candidates(con, g, p, best_known, hop_to, now=None):
    """-> [(eff ISK/hr, label, step text, note)] for every live lead."""
    from .catalog import runs_for, status
    now = now or time.time()
    acts = {a["id"]: a for a in status(con, getattr(p, "wallet_isk", 0.0))}
    out = []
    for ld in load():
        act = acts.get(ld.get("activity"))
        if not act or not act["unlocked"] or now > ld["seen"] + ld.get("life_h", 2) * 3600:
            continue
        if ld.get("needs") not in (None, "", "salvager", "look"):
            continue                                                    # not doable yet: listed by waiting() in the long view
        if ld.get("needs") == "look":
            c = _look_candidate(con, g, p, ld, best_known, hop_to, now)
            if c:
                out.append(c)
            continue
        here, there = p.current_system, ld["system"]
        needs_ship = ld.get("ship_word") if (ld.get("needs") == "salvager" and not p.can_salvage) else None
        j1 = j2 = 0
        fetch = None
        if needs_ship:
            fetch = _ship_system(con, g, p, needs_ship)
            if not fetch:
                continue
            j1 = _jumps(g, p, here, fetch[1])
            j2 = _jumps(g, p, fetch[1], there)
            if j1 is None or j2 is None:
                continue
        else:
            j2 = _jumps(g, p, here, there)
            if j2 is None:
                continue
        travel = (j1 + j2) * JUMP_MIN + (SWAP_MIN if needs_ship else 0.0)
        if now + travel * 60 > ld["seen"] + ld.get("life_h", 2) * 3600:
            continue                                                    # the wrecks will be gone before you get there
        n, rate = runs_for(con, act)
        work = max(10.0, ld.get("count", 20) * getattr(p, "salvage_wreck_seconds", 25.0) / 60.0 * 1.5)
        if rate:
            base, how = rate, f"your own rate from {n} timed run(s) of this activity"
        else:
            base, how = best_known, "UNKNOWN: modeled equal to the best ISK/hr on the list until you time a salvage run"
        eff = base * work / (work + travel)
        if here == there and not needs_ship:
            text = (f"STEP: SALVAGE the wrecks at {there}\n   DO ONLY THIS: in your salvager ship, approach the wrecks (Overview: Wrecks), lock, salvage each one. Salvage only: do NOT loot "
                    f"wrecks or cans that belong to other players (that flags you).\n   Seen: {ld['what']}\n   LATER: about {work:.0f} min for ~{ld.get('count', 0)} wrecks; sell the salvage at the best buy order")
        elif fetch and fetch[1] == here:
            text = (f"STEP: BOARD your {fetch[0]} (it carries the salvager)\n   DO ONLY THIS: station window > Hangars > Ship Hangar > right-click {fetch[0]} > Board Ship.\n"
                    f"   LATER: fly to {there} ({j2} jumps) and salvage: {ld['what']}")
        else:
            tgt = fetch[1] if fetch else there
            text = hop_to(tgt, (f"your {fetch[0]} (salvager) is there, then salvage at {there}" if fetch else f"salvage the wrecks at {there}: {ld['what']}"), [])
        if not text:
            continue
        mins_left = (ld["seen"] + ld.get("life_h", 2) * 3600 - now) / 60.0
        out.append((eff, f"salvage lead ({there})", text,
                    f"seen by directional scan, gone in about {mins_left:.0f} min; rate: {how}; {travel:.0f} min travel counted"))
    return out


def waiting(now=None):
    """Seen leads that cannot be done yet (no probes, no combat-ready ship, unknown type): lines for the long view, each an UNKNOWN to model once it can be done."""
    now = now or time.time()
    out = []
    for ld in load():
        if now > ld["seen"] + ld.get("life_h", 2) * 3600 or ld.get("needs") in (None, "", "salvager"):
            continue
        need = {"probes": "needs probe launcher + core scanner probes", "combat": "needs a combat-ready ship (99% rule)"}.get(ld["needs"], "type unknown")
        out.append(f"   SEEN at {ld['system']}: {ld['what']}  [{need}; unknown ISK/hr: modeled equal to your best until it can be done and timed]")
    return out


def _look_candidate(con, g, p, ld, best_known, hop_to, now):
    """An agent whose mission can only be read by docking at ITS station: one short step whose value is learning the mission (it then joins the plan at its own ISK/hr).
    Until it is read the mission is an UNKNOWN modeled equal to the best ISK/hr, minus the dock-and-read time and the travel."""
    here, there = p.current_system, ld["system"]
    j = _jumps(g, p, here, there)
    if j is None:
        return None
    docked_at = ""
    try:
        r = con.execute("SELECT name FROM stations WHERE station_id=?", (int(getattr(p, "current_location_id", 0) or 0),)).fetchone()
        docked_at = (r[0] or "") if r else ""
    except Exception:                                                   # noqa: BLE001
        pass
    at_station = bool(docked_at) and ld.get("station", "").lower() in docked_at.lower()
    read_min = 5.0
    travel = j * JUMP_MIN + (0.0 if (here != there or at_station) else 3.0)
    task = float(ld.get("task_min", 25))
    eff = best_known * task / (task + read_min + travel)
    agent = ld.get("agent", "the agent")
    if at_station:
        text = (f"STEP: OPEN {agent}'s offer in {there} (about 1 minute)\n   DO ONLY THIS: station window > Agents tab > {agent} > Start Conversation. Read the mission, send me the window, do NOT accept.\n"
                "   LATER: the mission joins the plan at its own ISK/hr")
    elif here == there:
        sid = 0
        try:
            r = con.execute("SELECT station_id FROM stations WHERE name LIKE ?", ("%" + ld.get("station", "") + "%",)).fetchone()
            sid = int(r[0]) if r else 0
        except Exception:                                               # noqa: BLE001
            pass
        head = f"STEP: DOCK at {ld.get('station', 'the agent station')} (about 2 minutes)"
        if sid:
            try:
                from .tradestep import STATION
                STATION[head] = sid
            except Exception:                                           # noqa: BLE001
                pass
        text = f"{head}\n   DO ONLY THIS: dock at {ld.get('station', 'the station')} (the game destination is set to it).\n   LATER: open {agent}'s conversation: the mission can only be read there"
    else:
        text = hop_to(there, f"{agent}'s mission can only be read at {ld.get('station', 'her station')}: dock there and open the conversation", [])
    if not text:
        return None
    return (eff, f"read {agent}'s mission", text, f"UNKNOWN mission ({ld['what']}): modeled equal to the best ISK/hr minus {read_min + travel:.0f} min of docking and reading, until read")
