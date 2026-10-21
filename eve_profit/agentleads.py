"""EVERY mission agent in the game data near you is a plan on the one list, without you checking what is near. The game data (agents table) carries where each agent is,
its level and division; it does NOT carry the missions (the game shows them only when you are docked at the agent's station). So an agent you have not read is an UNKNOWN
mission: modeled from its division's activity (Security -> Level 1 security missions, Mining, Distribution -> courier) like any untimed activity (expected ISK/hr x risk +
value of information), charged the dock-and-read time and the travel. Reading it (one short step per station) turns it into a known offer (agent_offers.json, from your
screenshot) that is ranked by its real ISK/hr. One candidate per STATION, best agent first, at most ten on the list. Each station is offered once per 12 hours."""
from .health import record as _hrec
import json
import time

TYPE_ACTIVITY = {"Security": "agent_l1_security", "Mining": "agent_mining_l1", "Distribution": "courier"}
SHOWN_KEY = "agentleads_shown"
READ_MIN = 5.0
JUMP_MIN = 3.0
MAX_JUMPS = 6
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


NONE_KEY = "agentleads_none"
MIN_STANDING = {1: -2.0, 2: 1.0}                                        # effective standing an agent of this level needs (best of agent, corporation, faction)


def _none(con):
    try:
        r = con.execute("SELECT value FROM meta WHERE key=?", (NONE_KEY,)).fetchone()
        return set(json.loads(r[0])) if r else set()
    except Exception:                                                   # noqa: BLE001
        return set()


def eligible(con, row, standing, hidden=None):
    """Can YOU see this agent? Not when you reported it hidden (`noagents`), when any of your standings with it, its corporation or its faction is below the level's minimum,
    or when the best of the three does not reach it. Agents you are not eligible for are never viewable in the game, so they are never a plan."""
    hidden = _none(con) if hidden is None else hidden
    if int(row["agent_id"]) in hidden:
        return False
    try:
        fac = con.execute("SELECT faction_id FROM corp_faction WHERE corporation_id=?", (row["corporation_id"],)).fetchone()
    except Exception:                                                   # noqa: BLE001
        fac = None
    sts = [standing.get(row["agent_id"], 0.0), standing.get(row["corporation_id"], 0.0)] + ([standing.get(fac[0], 0.0)] if fac and fac[0] else [])
    return max(sts) >= MIN_STANDING.get(int(row["level"]), 99.0) and min(sts) > -5.0


def hide_here(con, p, name=""):
    """`noagents`: the agents of the station you are docked in (or the one agent called `name`) are not viewable for you: remember it for good. -> number hidden."""
    docked = int(getattr(p, "current_location_id", 0) or 0)
    hidden = _none(con)
    n = 0
    if name:
        for r in con.execute("SELECT agent_id FROM agent_names WHERE name LIKE ?", (f"%{name}%",)):
            hidden.add(int(r[0]))
            n += 1
    elif docked:
        known = _known_agent_names()
        names = {r[0]: r[1] for r in con.execute("SELECT agent_id,name FROM agent_names")}
        for r in con.execute("SELECT agent_id FROM agents WHERE agent_type=2 AND location_id=?", (docked,)):
            if (names.get(r[0], "") or "").lower() not in known:
                hidden.add(int(r[0]))
                n += 1
    con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (NONE_KEY, json.dumps(sorted(hidden))))
    con.commit()
    return n


def _known_places():
    """Lower-cased text of every recorded offer (agent, where, mission): a station named there was already READ, even when its agents' names are not resolved yet."""
    import os
    try:
        offers = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent_offers.json"), encoding="utf-8")).get("offers", [])
    except (OSError, ValueError):
        return ""
    return "\n".join(f"{o.get('agent', '')} {o.get('where', '')}" for o in offers).lower()


def _station_known(con, loc, places):
    try:
        r = con.execute("SELECT name FROM stations WHERE station_id=?", (loc,)).fetchone()
    except Exception:                                                   # noqa: BLE001
        return False
    return bool(r and r[0] and r[0].lower() in places)


def _rate(act, best_known):
    """An unread agent's mission is worth the best known ISK/hr right now (owner rule 2026-10-21, same as untested activities);
    the caller discounts it for the read and the travel. The division's prior is only the fallback when nothing is known."""
    if best_known > 0:
        return float(best_known)
    from .catalog import INFO_WEIGHT, RISK_HAIRCUT, voi
    lo, hi = act["prior"]
    return (lo + hi) / 2.0 * (1.0 - RISK_HAIRCUT.get(act.get("risk", "low"), 0.0)) + INFO_WEIGHT * voi({**act, "runs": 0}, best_known)


def candidates(con, g, p, best_known, hop_to, now=None, limit=10):
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
    places = _known_places()
    hidden = _none(con)
    shown = _shown(con)
    docked = int(getattr(p, "current_location_id", 0) or 0)
    best = {}                                                           # station -> (eff, agents)
    q = ",".join(str(d) for d in DIV_ACTIVITY)
    for r in con.execute(f"SELECT agent_id,corporation_id,location_id,system_id,level,division_id FROM agents WHERE agent_type=2 AND level<=2 AND division_id IN ({q})"):
        sid = r["system_id"]
        if sid not in reach or g.sec[sid] < SAFE:
            continue
        if not eligible(con, r, standing, hidden):
            continue
        nm = names.get(r["agent_id"], "")
        if nm.lower() in known or now - shown.get(str(r["location_id"]), 0) < 12 * 3600 or _station_known(con, r["location_id"], places):
            continue
        act = acts.get(DIV_ACTIVITY[r["division_id"]])
        if not act:
            continue
        j = reach[sid].jumps
        work = float(act.get("minutes") or 25)
        eff = _rate(act, best_known) * work / (work + READ_MIN + j * JUMP_MIN)
        cur_best = best.get(sid)                                        # one candidate per SYSTEM (the best agent's station is where you dock)
        item = {"loc": r["location_id"], "id": r["agent_id"], "name": nm or f"a level {r['level']} {DIV_NAME[r['division_id']]} agent", "level": r["level"], "div": DIV_NAME[r["division_id"]],
                "system": g.name[sid], "jumps": j, "eff": eff, "act": act["name"]}
        if cur_best is None:
            best[sid] = [eff, [item]]
        else:
            cur_best[1].append(item)
            cur_best[0] = max(cur_best[0], eff)
    out = []
    for _sid, (eff, items) in sorted(best.items(), key=lambda kv: -kv[1][0])[:limit]:
        items.sort(key=lambda x: -x["eff"])
        top = items[0]
        loc = top["loc"]
        items = [i for i in items if i["loc"] == loc]                    # the agents of that station: one dock, one read
        st = con.execute("SELECT name FROM stations WHERE station_id=?", (loc,)).fetchone()
        sname = (st[0] if st and st[0] else "") or f"a station in {top['system']}"
        who = ", ".join(f"{i['name']} (L{i['level']} {i['div']})" for i in items[:3])
        if docked == loc:
            text = (f"STEP: READ the agents at {sname} (about {READ_MIN:.0f} minutes)\\n   DO ONLY THIS: station window > Agents tab: {who}. Orange 'Offered' = a mission is waiting: send me those windows (do not accept yet). An agent you cannot see in that list is not available to you: run  python -m eve_profit noagents\\n"
                    "   LATER: each mission joins the plan at its own ISK/hr").replace("\\n", "\n")
            here_station = True
        elif top["system"] == p.current_system:
            head = f"STEP: DOCK at {sname} (about 2 minutes)"
            try:
                from .tradestep import STATION
                STATION[head] = int(loc)
            except Exception as _he:                                           # noqa: BLE001
                _hrec('agentleads', _he)
            text = f"{head}\n   DO ONLY THIS: dock at {sname} (the game destination is set to it).\n   ALSO, same stop: read the agents there ({who}): station window > Agents tab, send me the orange 'Offered' windows (do not accept yet)."
            here_station = False
        else:
            text = hop_to(top["system"], f"{who} at {sname}: dock and read their missions", [])
            here_station = False
        if not text:
            continue
        out.append((eff, f"read agents at {top['system']}", text,
                    f"{len(items)} agent(s) from the game data, missions unknown until read: modeled as your best known ISK/hr (owner rule) minus {READ_MIN + top['jumps'] * JUMP_MIN:.0f} min of docking, reading and travel"))
    return out


def mark_read(con, p, now=None):
    """The READ step was shown for the station you are docked in: do not offer it again for 12 hours."""
    shown = _shown(con)
    shown[str(int(getattr(p, "current_location_id", 0) or 0))] = now or time.time()
    con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (SHOWN_KEY, json.dumps(shown)))
    con.commit()


def here_note(con, p, now=None):
    """Agents of the station you are docked in whose missions are not modeled yet: ONE extra line for whatever step you do here (dock = also read). '' when none.
    Marks the station read for 12 hours."""
    docked = int(getattr(p, "current_location_id", 0) or 0)
    if not docked:
        return ""
    now = now or time.time()
    try:
        if now - _shown(con).get(str(docked), 0) < 12 * 3600 or _station_known(con, docked, _known_places()):
            return ""
        from .agentmap import get_map
        div = get_map(con)
        q = ",".join(str(int(d)) for d in div) or "0"
        known = _known_agent_names()
        names = {r[0]: r[1] for r in con.execute("SELECT agent_id,name FROM agent_names")} if "agent_names" in {r[0] for r in con.execute("SELECT name FROM sqlite_master")} else {}
        standing = {r[0]: r[1] for r in con.execute("SELECT from_id,standing FROM standings")}
        rows = [r for r in con.execute(f"SELECT agent_id,corporation_id,level,division_id FROM agents WHERE agent_type=2 AND level<=2 AND location_id=? AND division_id IN ({q})", (docked,))
                if eligible(con, r, standing)]
    except Exception:                                                   # noqa: BLE001
        return ""
    who = [f"{names.get(r['agent_id']) or 'a level %d agent' % r['level']} (L{r['level']} {div[r['division_id']]})" for r in rows
           if (names.get(r["agent_id"], "") or "").lower() not in known]
    if not who:
        return ""
    mark_read(con, p, now)
    return ("   ALSO, same dock (about 2 minutes): read the agents here, " + ", ".join(who[:4])
            + ": station window > Agents tab, send me the orange 'Offered' windows (do not accept yet); each mission then joins the plan at its own ISK/hr.")
