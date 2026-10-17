"""EVERY mission agent in the game data near you is a plan on the one list, without you checking what is near. The game data (agents table) carries where each agent is,
its level and division; it does NOT carry the missions (the game shows them only when you are docked at the agent's station). So an agent you have not read is an UNKNOWN
mission: modeled from its division's activity (Security -> Level 1 security missions, Mining, Distribution -> courier) like any untimed activity (expected ISK/hr x risk +
value of information), charged the dock-and-read time and the travel. Reading it (one short step per station) turns it into a known offer (agent_offers.json, from your
screenshot) that is ranked by its real ISK/hr. One candidate per STATION, best agent first, at most three on the list. Each station is offered once per 12 hours."""
import json
import time

TYPE_ACTIVITY = {"Security": "agent_l1_security", "Mining": "agent_mining_l1", "Distribution": "courier"}
SHOWN_KEY = "agentleads_shown"
READ_MIN = 5.0
JUMP_MIN = 3.0
MAX_JUMPS = 4
SAFE = 0.5
STANDING_FOR_LEVEL = {1: -10.0, 2: 1.0}


def _shown(con):
    try:
        r = con.execute("SELECT value FROM meta WHERE key=?", (SHOWN_KEY,)).fetchone()
        return json.loads(r[0]) if r else {}
    except Exception:                                                   # noqa: BLE001
        return {}


def _known_agent_names():
    import os
    try:
        offers = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent_offers.json"), encoding="utf-8")).get("offers", [])
    except (OSError, ValueError):
        return set()
    return {o.get("agent", "").split(" (")[0].lower() for o in offers}


def _rate(act, best_known):
    from .catalog import INFO_WEIGHT, RISK_HAIRCUT, voi
    lo, hi = act["prior"]
    return (lo + hi) / 2.0 * (1.0 - RISK_HAIRCUT.get(act.get("risk", "low"), 0.0)) + INFO_WEIGHT * voi({**act, "runs": 0}, best_known)


def candidates(con, g, p, best_known, hop_to, now=None, limit=3):
    """-> [(eff ISK/hr, label, step text, note)]"""
    from .catalog import load
    now = now or time.time()
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(agents)")}
        if "division_id" not in cols:
            return []
        cur = g.id_of(p.current_system)
        reach = g.reach(cur, MAX_JUMPS, p.avoid_yellow)
    except Exception:                                                   # noqa: BLE001
        return []
    from .agentmap import get_map
    DIV_NAME = get_map(con)                                             # division id -> Security / Mining / Distribution (calibrated from known agents)
    DIV_ACTIVITY = {d: TYPE_ACTIVITY[t] for d, t in DIV_NAME.items() if t in TYPE_ACTIVITY}
    acts = {a["id"]: a for a in load()}
    standing = {r[0]: r[1] for r in con.execute("SELECT from_id,standing FROM standings")}
    names = {r[0]: r[1] for r in con.execute("SELECT agent_id,name FROM agent_names")} if "agent_names" in {r[0] for r in con.execute("SELECT name FROM sqlite_master")} else {}
    known = _known_agent_names()
    shown = _shown(con)
    docked = int(getattr(p, "current_location_id", 0) or 0)
    best = {}                                                           # station -> (eff, agents)
    q = ",".join(str(d) for d in DIV_ACTIVITY)
    for r in con.execute(f"SELECT agent_id,corporation_id,location_id,system_id,level,division_id FROM agents WHERE agent_type=2 AND level<=2 AND division_id IN ({q})"):
        sid = r["system_id"]
        if sid not in reach or g.sec[sid] < SAFE:
            continue
        if r["level"] == 2 and max(standing.get(r["agent_id"], -10.0), standing.get(r["corporation_id"], -10.0)) < STANDING_FOR_LEVEL[2]:
            continue
        nm = names.get(r["agent_id"], "")
        if nm.lower() in known or now - shown.get(str(r["location_id"]), 0) < 12 * 3600:
            continue
        act = acts.get(DIV_ACTIVITY[r["division_id"]])
        if not act:
            continue
        j = reach[sid].jumps
        work = float(act.get("minutes") or 25)
        eff = _rate(act, best_known) * work / (work + READ_MIN + j * JUMP_MIN)
        cur_best = best.get(r["location_id"])
        item = {"id": r["agent_id"], "name": nm or f"a level {r['level']} {DIV_NAME[r['division_id']]} agent", "level": r["level"], "div": DIV_NAME[r["division_id"]],
                "system": g.name[sid], "jumps": j, "eff": eff, "act": act["name"]}
        if cur_best is None:
            best[r["location_id"]] = [eff, [item]]
        else:
            cur_best[1].append(item)
            cur_best[0] = max(cur_best[0], eff)
    out = []
    for loc, (eff, items) in sorted(best.items(), key=lambda kv: -kv[1][0])[:limit]:
        items.sort(key=lambda x: -x["eff"])
        top = items[0]
        st = con.execute("SELECT name FROM stations WHERE station_id=?", (loc,)).fetchone()
        sname = st[0] if st else top["system"]
        who = ", ".join(f"{i['name']} (L{i['level']} {i['div']})" for i in items[:3])
        if docked == loc:
            text = (f"STEP: READ the agents at {sname} (about {READ_MIN:.0f} minutes)\\n   DO ONLY THIS: station window > Agents tab: {who}. Orange 'Offered' = a mission is waiting: send me those windows (do not accept yet).\\n"
                    "   LATER: each mission joins the plan at its own ISK/hr").replace("\\n", "\n")
            here_station = True
        elif top["system"] == p.current_system:
            head = f"STEP: DOCK at {sname} (about 2 minutes)"
            try:
                from .tradestep import STATION
                STATION[head] = int(loc)
            except Exception:                                           # noqa: BLE001
                pass
            text = f"{head}\n   DO ONLY THIS: dock at {sname} (the game destination is set to it).\n   LATER: read the agents there: {who}"
            here_station = False
        else:
            text = hop_to(top["system"], f"{who} at {sname}: dock and read their missions", [])
            here_station = False
        if not text:
            continue
        out.append((eff, f"read agents at {top['system']}", text,
                    f"{len(items)} agent(s) from the game data, missions unknown until read: modeled as {top['act']} (prior) minus {READ_MIN + top['jumps'] * JUMP_MIN:.0f} min of docking, reading and travel"))
    return out


def mark_read(con, p, now=None):
    """The READ step was shown for the station you are docked in: do not offer it again for 12 hours."""
    shown = _shown(con)
    shown[str(int(getattr(p, "current_location_id", 0) or 0))] = now or time.time()
    con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (SHOWN_KEY, json.dumps(shown)))
    con.commit()
