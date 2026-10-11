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
    if here == dest:
        if st.get("arrived"):                                           # the sell step was shown once already: the haul is over
            clear(con)
            return None
        st["arrived"] = True
        save(con, st)
        text = "\n".join([f"STEP: SELL YOUR HAULED STOCK in {dest} - about {st['net']:,.0f} ISK", "   DO ONLY THIS: dock and sell to the HIGHEST buy orders (Market > item > Sell):"] + items
                         + ["   After this `next` chooses the best step from here: there is no planned trip back."])
        return 1e12, text                                               # you are there with the goods: finishing the sale comes first
    if st.get("looked") != here and here != st["origin"]:
        st["looked"] = here                                             # shown once per stop: the next `next` flies on
        save(con, st)
        from .haul import agents_here
        ag = agents_here(here, g, p)
        text = "\n".join([f"STEP: LOOK AROUND {here} (about 1 minute)", "   DO ONLY THIS: before flying on, check this system for agents and missions you can do here:"]
                          + (["      " + x for x in ag] if ag else ["      no known agent within 2 jumps: open the Agency (left side) > Agents & Missions to look further"])
                          + ["   HOW TO TELL: dock, station window (right side) > Agents tab. An orange 'Offered' beside a name = a mission is waiting. No 'Offered' = nothing here.",
                             "   Orange 'Offered' on a NEW agent or mission? Send me only that agent's window. No orange? Run  python -m eve_profit next  (it flies on)."])
        return 1e11, text
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
