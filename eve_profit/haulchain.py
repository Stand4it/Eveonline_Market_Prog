"""A haul as ONE JUMP AT A TIME. The tool remembers the haul (meta 'haul_chain') because your ship's cargo is invisible to `sync`, so once the stock
leaves the hangar it can no longer see it. At every stop `next` plans again: the haul only continues if it is still the best step (a started haul
gets a 25% head start so the plan does not flip-flop); at the destination the step is to sell, and after that the best next step is chosen fresh.
There is no planned return trip."""
from .health import record as _hrec
import json
import time

KEY = "haul_chain"
MAX_AGE_S = 72 * 3600          # a long trip with sleep and detours must not make the planner forget the cargo (12 h did)
MIN_PER_JUMP = 2.0            # minutes per jump, from the timed flights
ASSET_LAG_S = 3600            # the game's asset list can be this stale when a haul is planned
STICKY = 1.25                # a started haul keeps going unless something else pays this many times more


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
    except Exception as _he:                                                   # noqa: BLE001
        _hrec('haulchain', _he)


def make(h, origin):
    return {"t": time.time(), "origin": origin, "dest": h["dest"], "total": h["jumps"], "gain": h["gain"], "net": h["net"],
            "gain_stock": h.get("gain_stock", h["gain"]), "extra": h.get("extra_isk", 0.0),
            "items": [[n, int(q), float(net), float(local)] for n, q, net, local in h["items"][:8]], "ore": bool(h.get("ore")), "arrived": False, "t0": time.time()}


def _held_at_origin(con, g, st):
    """True while the stock is still in the origin hangar (the haul has not started)."""
    try:
        sid = g.id_of(st["origin"])
        for name, qty, _, _ in st["items"]:
            r = con.execute("SELECT COALESCE(SUM(i.quantity),0) FROM inventory i JOIN types t ON t.type_id=i.type_id WHERE t.name=? COLLATE NOCASE AND i.system_id=?", (name, sid)).fetchone()
            if int(r[0] or 0) >= max(1, qty // 2):
                return True
    except Exception as _he:                                                   # noqa: BLE001
        _hrec('haulchain', _he)
    return False


HERE_RATE = 1_000_000.0          # ISK/hr a minute of flying is worth when comparing "sell here now" with "carry on"


def _held(con):
    """{type name lower: units in your ship's cargo} (cargo_now, read at sync), {} when unknown."""
    try:
        r = con.execute("SELECT value FROM meta WHERE key='cargo_now'").fetchone()
        cargo = json.loads(r[0]) if r else {}
        names = {int(t): n for t, n in con.execute("SELECT type_id,name FROM types")}
        return {names[int(t)].lower(): int(q) for t, q in cargo.items() if int(t) in names}
    except Exception as _he:                                            # noqa: BLE001
        _hrec('haulchain', _he)
        return {}


def _sold_since(con, st):
    """{type name lower: units you SOLD (wallet transactions) since the haul's stock was counted}: stock already sold is no longer hauled.
    The game's asset list lags up to an hour, so a haul can be planned from stock sold minutes before: sales count from ASSET_LAG_S before
    the haul started (but never before your last buy of that item, so an older lot sold earlier does not count)."""
    try:
        t0 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.get("t0", st.get("t", 0)) - ASSET_LAG_S))
        rows = con.execute("SELECT LOWER(t.name), SUM(x.quantity) FROM transactions x JOIN types t ON t.type_id=x.type_id "
                           "WHERE x.is_buy=0 AND x.date>=MAX(?, COALESCE((SELECT MAX(b.date) FROM transactions b WHERE b.type_id=x.type_id AND b.is_buy=1), '')) "
                           "GROUP BY t.name", (t0,)).fetchall()
        return {n: int(q or 0) for n, q in rows}
    except Exception as _he:                                            # noqa: BLE001
        _hrec('haulchain', _he)
        return {}


def _sell_here(con, g, p, st, here):
    """The stock you really carry, sold at the buy orders in THIS system (NPC stations and structures you can read), against carrying on to the destination.
    -> (net here, per-item rows [(name, qty, net)], station id of the best order) when selling here beats carrying on (the destination's net minus the time the rest of the flight costs), else None."""
    from .orders import load_books, sell_into_bids
    try:
        sid = g.id_of(here)
        r = g.route(sid, g.id_of(st["dest"]), 60, p.avoid_yellow)
        left = r.jumps if r else 0
    except Exception as _he:                                            # noqa: BLE001
        _hrec('haulchain', _he)
        return None
    held = _held(con)
    _, buys = load_books(con, {sid})
    tot_here = tot_dest = 0.0
    rows, loc = [], 0
    for name, q, net_dest, _local in st["items"]:
        have = held.get(name.lower(), q) if held else q
        have = min(have, q)
        if have <= 0:
            continue
        row = con.execute("SELECT type_id FROM types WHERE name=? COLLATE NOCASE", (name,)).fetchone()
        if not row:
            continue
        bids = buys.get(row[0], {}).get(sid, [])
        sold, net = sell_into_bids(bids, have, p.sales_tax)
        if sold < have * 0.5:
            continue                                                    # the buyers here take too little of it
        rows.append((name, sold, net))
        tot_here += net
        tot_dest += net_dest * have / max(q, 1)
        if not loc:
            b = con.execute("SELECT location_id FROM orders WHERE type_id=? AND is_buy=1 AND system_id=? AND volume_remain>0 ORDER BY price DESC LIMIT 1", (row[0], sid)).fetchone()
            loc = int(b[0]) if b and b[0] else 0
    if not rows:
        return None
    minutes = left * max(p.jump_seconds / 60.0, MIN_PER_JUMP) + 2.0
    if tot_here >= tot_dest - HERE_RATE * minutes / 60.0:
        return tot_here, rows, loc
    return None


def candidate(con, g, p):
    """The haul in progress as a `next` candidate: (rate ISK/hr, text) or None (no haul, not started yet, or finished)."""
    st = load(con)
    if not st:
        return None
    here, dest = p.current_system, st["dest"]
    st["t"] = time.time()                                               # still in use: keep it alive
    try:
        save(con, st)
    except Exception as _he:                                                   # noqa: BLE001
        _hrec('haulchain', _he)
    if here == st["origin"] and _held_at_origin(con, g, st):
        return None                                                     # not started: the normal haul candidate handles it
    held_ = _held(con)
    sold_ = _sold_since(con, st)
    scaled = []                                                         # the plan's quantities are capped at what you really carry, minus what you already sold
    for n_, q_, net_, loc_ in st["items"]:
        have_ = min(q_, held_.get(n_.lower(), q_)) if held_ else q_
        have_ = min(have_, q_ - sold_.get(n_.lower(), 0))
        if have_ > 0:
            scaled.append([n_, have_, net_ * have_ / max(q_, 1), loc_])
    if not scaled and sold_:                                            # everything in the haul is sold already: the haul is over
        clear(con)
        return None
    if scaled:
        st = dict(st, items=scaled, net=sum(x[2] for x in scaled))
    worth = [it for it in st["items"] if it[2] >= 5_000.0][:4] or st["items"][:1]            # only stacks worth a line (cosmetic odds and ends ride along unlisted)
    items = [f"      {q:>9,} x {n:<32} ~{net:>11,.0f} at {dest}" for n, q, net, local in worth]
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
        try:                                                            # passing a market that pays as much as the destination (after the flight's time): SELL HERE, the ISK comes sooner
            sh = _sell_here(con, g, p, st, here)
        except Exception as _he:                                        # noqa: BLE001
            _hrec('haulchain', _he)
            sh = None
        if sh:
            net_here, rows_here, loc = sh
            st["dest"], st["net"], st["arrived"] = here, net_here, True
            st["items"] = [[n, int(q), float(net), 0.0] for n, q, net in rows_here]
            save(con, st)
            head = f"STEP: SELL YOUR HAULED STOCK in {here} - about {net_here:,.0f} ISK"
            try:
                from .tradestep import STATION
                if loc:
                    STATION[head] = loc                                 # the game destination = the station or structure with the best buy order
            except Exception as _he:                                    # noqa: BLE001
                _hrec('haulchain', _he)
            lines = [head, f"   {here} pays as much as the destination, and it is here and now (no more flying): dock and sell to the HIGHEST buy orders (Market > item > Sell):"] \
                + [f"      {q:>9,} x {n:<32} ~{net:>11,.0f}" for n, q, net in rows_here] + ["   After this `next` chooses the best step from here: there is no planned trip back."]
            return 1e12, "\n".join(lines)
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
    minutes = left * max(p.jump_seconds / 60.0, MIN_PER_JUMP) + 2.0                # your measured flights run 1-3 min a jump (align, warp, gate, dock), not 45 s
    stock_gain = st["gain_stock"] if "gain_stock" in st else sum(net - local for _, _, net, local in st["items"])      # an older chain: the stock's own gain from its items
    gain = stock_gain + 0.5 * st.get("extra", 0.0)           # the stock you hold is certain; the optional trades on the way are counted at half
    rate = gain * 60.0 / max(minutes, 1.0)
    lines = [f"STEP: FLY to {g.name[r.path[1]]} - jump {k} of {st['total']}, hauling your stock to {dest}"] + items
    lines.append(f"   DO ONLY THIS: fly to {g.name[r.path[1]]} and stop there. Then run  python -m eve_profit next  (it plans again from there: {left} jumps left to {dest}, no planned trip back).")
    try:
        from .dailygoals import _on_the_way
        way = _on_the_way(con, g, p, dest)
        if way:
            lines.append("   ON THE WAY (optional; confirm each buy with `check` first):")
            lines += [f"      {x}" for x in way]
    except Exception as _he:                                                   # noqa: BLE001
        _hrec('haulchain', _he)
    try:
        from .haul import agents_on_route
        lines += ["   " + x for x in agents_on_route(g, p, dest)]
    except Exception as _he:                                                   # noqa: BLE001
        _hrec('haulchain', _he)
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
    try:
        from .agentleads import _known_agent_names
        known = _known_agent_names()
        names = [n for n in names if n.lower() not in known]            # an agent whose offer is already recorded is not "looked at" again: that offer is a plan of its own (accept / deliver)
    except Exception as _he:                                                   # noqa: BLE001
        _hrec('haulchain', _he)
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
            except Exception as _he:                                           # noqa: BLE001
                _hrec('haulchain', _he)
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


def fold_legs(con, st):
    """The sale ended the haul: add the hours (and ISK) of its timed flight legs to the newest run, so the haul's ISK/hr includes the hauling time."""
    try:
        since = st.get("t0") or (time.time() - MAX_AGE_S)
        last = con.execute("SELECT id, isk, hours FROM activity_log ORDER BY id DESC LIMIT 1").fetchone()
        if not last:
            return ""
        legs = con.execute("SELECT id, isk, hours FROM activity_log WHERE id<? AND ts>=? AND (activity LIKE 'Hauling%' OR activity LIKE 'Fly %') ORDER BY id", (last[0], since)).fetchall()
        if not legs:
            return ""
        h = sum(r[2] for r in legs)
        i = sum(r[1] for r in legs)
        con.execute("UPDATE activity_log SET isk=isk+?, hours=hours+? WHERE id=?", (i, h, last[0]))
        con.executemany("DELETE FROM activity_log WHERE id=?", [(r[0],) for r in legs])
        con.commit()
        tot_h, tot_i = last[2] + h, last[1] + i
        return f"Haul timed as one run: {len(legs)} flight legs + the sale = {tot_h * 60:.0f} min, {tot_i:,.0f} ISK = {tot_i / max(tot_h, 1e-9):,.0f} ISK/hr."
    except Exception:                                                   # noqa: BLE001
        return ""
