"""A haul as ONE JUMP AT A TIME. The tool remembers the haul (meta 'haul_chain') because your ship's cargo is invisible to `sync`, so once the stock
leaves the hangar it can no longer see it. At every stop `next` plans again: the haul only continues if it is still the best step (a started haul
gets a 25% head start so the plan does not flip-flop); at the destination the step is to sell, and after that the best next step is chosen fresh.
There is no planned return trip."""
import json
import time

KEY = "haul_chain"
MAX_AGE_S = 12 * 3600
STICKY = 1.25                 # a started haul keeps going unless something else pays this many times more


def load(con):
    try:
        r = con.execute("SELECT value FROM meta WHERE key=?", (KEY,)).fetchone()
        st = json.loads(r[0]) if r else None
    except Exception:                                                   # noqa: BLE001
        return None
    if st and time.time() - st.get("t", 0) > MAX_AGE_S:
        return None
    return st


def save(con, st):
    con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (KEY, json.dumps(st)))
    con.commit()


def clear(con):
    try:
        con.execute("DELETE FROM meta WHERE key=?", (KEY,))
        con.commit()
    except Exception:                                                   # noqa: BLE001
        pass


def make(h, origin):
    return {"t": time.time(), "origin": origin, "dest": h["dest"], "total": h["jumps"], "gain": h["gain"], "net": h["net"],
            "items": [[n, int(q), float(net), float(local)] for n, q, net, local in h["items"][:8]], "ore": bool(h.get("ore")), "arrived": False}


def _held_at_origin(con, g, st):
    """True while the stock is still in the origin hangar (the haul has not started)."""
    try:
        sid = g.id_of(st["origin"])
        for name, qty, _, _ in st["items"]:
            r = con.execute("SELECT COALESCE(SUM(i.quantity),0) FROM inventory i JOIN types t ON t.type_id=i.type_id WHERE t.name=? COLLATE NOCASE AND i.system_id=?", (name, sid)).fetchone()
            if int(r[0] or 0) >= max(1, qty // 2):
                return True
    except Exception:                                                   # noqa: BLE001
        pass
    return False


def candidate(con, g, p):
    """The haul in progress as a `next` candidate: (rate ISK/hr, text) or None (no haul, not started yet, or finished)."""
    st = load(con)
    if not st:
        return None
    here, dest = p.current_system, st["dest"]
    if here == st["origin"] and _held_at_origin(con, g, st):
        return None                                                     # not started: the normal haul candidate handles it
    items = [f"      {q:>9,} x {n:<32} ~{net:>11,.0f} at {dest}" for n, q, net, local in st["items"][:6]]
    if here != dest and st.get("arrived"):                              # you were at the destination and have left: the haul is over (no trip back)
        clear(con)
        return None
    if here == dest:
        if not st.get("arrived"):
            st["arrived"] = True
            save(con, st)                                               # the sell step stays until you stop its timer (or `done --goal sold`)
        text = "\n".join([f"STEP: SELL YOUR HAULED STOCK in {dest} - about {st['net']:,.0f} ISK", "   DO ONLY THIS: dock and sell to the HIGHEST buy orders (Market > item > Sell):"] + items
                         + ["   After this `next` chooses the best step from here: there is no planned trip back."])
        return 1e12, text                                               # you are there with the goods: finishing the sale comes first
    if here != st["origin"]:
        step = _look_around(con, g, p, st, here)
        if step:
            return 1e11, step
    try:
        r = g.route(g.id_of(here), g.id_of(dest), 60, p.avoid_yellow)
    except Exception:                                                   # noqa: BLE001
        r = None
    if not r or len(r.path) < 2:
        return None
    left = r.jumps
    k = max(1, st["total"] - left + 1)
    minutes = left * p.jump_seconds / 60.0 + 2.0
    rate = st["gain"] * 60.0 / max(minutes, 1.0)
    lines = [f"STEP: FLY to {g.name[r.path[1]]} - jump {k} of {st['total']}, hauling your stock to {dest}"] + items
    lines.append(f"   DO ONLY THIS: fly to {g.name[r.path[1]]} and stop there. Then run  python -m eve_profit next  (it plans again from there: {left} jumps left to {dest}, no planned trip back).")
    try:
        from .dailygoals import _on_the_way
        way = _on_the_way(con, g, p, dest)
        if way:
            lines.append("   ON THE WAY (optional; confirm each buy with `check` first):")
            lines += [f"      {x}" for x in way]
    except Exception:                                                   # noqa: BLE001
        pass
    try:
        from .haul import agents_on_route
        lines += ["   " + x for x in agents_on_route(g, p, dest)]
    except Exception:                                                   # noqa: BLE001
        pass
    return rate * STICKY, "\n".join(lines)


def _station_of(con, g, here):
    """(station id, name) of an NPC station in `here` (the first one), or (0, '')."""
    try:
        r = con.execute("SELECT station_id,name FROM stations WHERE system_id=? ORDER BY station_id LIMIT 1", (g.id_of(here),)).fetchone()
        return (int(r[0]), r[1] or "") if r else (0, "")
    except Exception:                                                   # noqa: BLE001
        return 0, ""


def _look_around(con, g, p, st, here):
    """Agents in the system you stopped in, ONE STEP EACH: first dock (the destination is set to the station), then open each agent's window, then fly on.
    State st['looked_here'] = {system, agents: [done names]}."""
    from .haul import agents_here
    ag = [x for x in agents_here(here, g, p) if x.startswith("HERE")]
    if not ag:
        return ""
    names = []
    ready = None
    for x in ag:
        try:
            nm = x.split(": ", 1)[1].split(" (")[0]
        except IndexError:
            continue
        if "(security)" in x:                                           # security missions are combat and are read only at the agent's station: they are a planned 'read the mission' lead (leads.py), not a stop on a haul
            continue
        names.append(nm)
    lh = st.get("looked_here") or {}
    if lh.get("system") != here:
        lh = {"system": here, "agents": []}
    here_station = _docked_station(con, p)
    names = [n for n in names if _agent_here(n, here_station)]          # only agents whose station you are docked in (agents elsewhere in the system wait)
    todo = [n for n in names if n not in lh["agents"]]
    if not todo:
        return ""
    docked = (getattr(p, "current_location_id", 0) or 0) > 0
    st["looked_here"] = lh
    if not docked:
        sid, sname = _agent_station_id(con, g, here, todo[0])                # dock where the agent is
        if not sid:
            sid, sname = _station_of(con, g, here)
        head = f"STEP: DOCK at {sname or 'a station'} in {here} (about 1 minute)"
        if sid:
            try:
                from .tradestep import STATION
                STATION[head] = sid
            except Exception:                                           # noqa: BLE001
                pass
        save(con, st)
        return "\n".join([head, f"   DO ONLY THIS: dock at {sname or 'the station'} (the game destination is set to it: autopilot / right-click the station > Dock).",
                           f"   LATER: {len(todo)} agent(s) here, one step each: {', '.join(todo)}"])
    agent = todo[0]
    lh["agents"].append(agent)                                          # shown once: the next `next` gives the next agent, then flies on
    save(con, st)
    more = f"   LATER: then {', '.join(todo[1:])}" if len(todo) > 1 else "   LATER: then `next` flies on"
    return "\n".join([f"STEP: OPEN {agent}'s offer in {here} (about 1 minute)",
                      f"   DO ONLY THIS: station window > Agents tab > {agent} > Start Conversation. Orange 'Offered' = a mission is waiting: send me that window (do not accept yet unless I say so).",
                      more])


def _docked_station(con, p):
    try:
        r = con.execute("SELECT name FROM stations WHERE station_id=?", (int(getattr(p, "current_location_id", 0) or 0),)).fetchone()
        return (r[0] or "") if r else ""
    except Exception:                                                   # noqa: BLE001
        return ""


def _agent_station(name):
    import json
    import os
    try:
        d = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agents_nearby.json"), encoding="utf-8"))
        for kind in ("security", "mining", "distribution_nearest", "locator_nearest", "rd_nearest"):
            for a in d.get(kind, []):
                if a.get("agent") == name:
                    return a.get("station", "")
    except (OSError, ValueError):
        pass
    return ""


def _agent_here(name, docked_name):
    """True when the agent may be in the station you are docked in: station unknown (not recorded yet) or equal; False when it is recorded elsewhere."""
    st = _agent_station(name)
    if not st:
        return True
    if st.lower().startswith("unknown"):
        return False
    return not docked_name or st.lower() in docked_name.lower() or docked_name.lower() in st.lower()


def _agent_station_id(con, g, here, name):
    st = _agent_station(name)
    if not st or st.lower().startswith("unknown"):
        return 0, ""
    try:
        r = con.execute("SELECT station_id,name FROM stations WHERE name LIKE ?", ("%" + st + "%",)).fetchone()
        return (int(r[0]), r[1]) if r else (0, "")
    except Exception:                                                   # noqa: BLE001
        return 0, ""


def _combat_ready(con, g, p):
    try:
        from .combatprep import prep_estimate
        return prep_estimate(con, g, p)[0] <= 0
    except Exception:                                                   # noqa: BLE001
        return False
