"""An agent mission as ONE STEP AT A TIME (the whole numbered block stays in `next --plan`): ACCEPT it in person -> fly to where it is done (one hop per
step, destination set) -> DO the mission and hand it in. State in meta 'agentchain': {"agent","stage","shown"}."""
import json

KEY = "agentchain"


def _load(con):
    try:
        r = con.execute("SELECT value FROM meta WHERE key=?", (KEY,)).fetchone()
        return json.loads(r[0]) if r else None
    except Exception:                                                   # noqa: BLE001
        return None


def _save(con, st):
    if st is None:
        con.execute("DELETE FROM meta WHERE key=?", (KEY,))
    else:
        con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (KEY, json.dumps(st)))
    con.commit()


def _brief(o):
    m = o.get("mission", "")
    return (m.split(":", 1)[-1] if ":" in m[:60] else m)[:170].strip()


CHEAP_ALT = {"mining": ["Civilian Miner"]}          # cheaper stand-ins that do the same job for one mission
ISK_PER_JUMP = 20_000.0                              # a jump of detour is worth this much when picking where to buy


def gear_step(con, g, p, o):
    """An offer that needs a tool you have not fitted (o['needs_tool'] = a key of tools.TOOLS): the step that gets it, BEFORE accepting
    (the bonus clock starts at accept). -> text or None (fitted, unknown tool, or no seller found)."""
    nt = o.get("needs_tool")
    try:
        from . import tools as _tl
        if not nt or nt not in _tl.TOOLS or _tl.fitted_now(con).get(nt, 0) >= 1:
            return None
        item, qty = _tl.TOOLS[nt]["buy"][0]
        label = _tl.TOOLS[nt]["label"]
        here = g.id_of(p.current_system)
        names = CHEAP_ALT.get(nt, []) + [item]
        held = con.execute("SELECT t.name FROM inventory i JOIN types t ON t.type_id=i.type_id WHERE i.system_id=? AND t.name IN (%s) AND i.quantity>=1"
                           % ",".join("?" * len(names)), [here] + names).fetchone()
        ship = (p.ship_name or "").split(" - ")[0] or "ship"
        if held:
            return (f"STEP: FIT {qty} x {held[0]} to your {ship} (needed for: {o['agent'].split(' (')[0]}'s mission)\n"
                    f"   DO ONLY THIS: open the fitting window (Alt+F) and drag the {held[0]} from the hangar into empty high slots. Then run  python -m eve_profit next")
        reach = g.reach(here, 10, p.avoid_yellow)
        import time as _t
        best = None
        for nm in names:
            for price, sid, loc in con.execute("SELECT o.price, o.system_id, o.location_id FROM orders o JOIN types t ON t.type_id=o.type_id WHERE t.name=? AND o.is_buy=0 "
                                               "AND o.volume_remain>=1 AND o.fetched_at>?", (nm, _t.time() - 2 * 86400)):
                if sid in reach:
                    score = price * qty + reach[sid].jumps * 2 * ISK_PER_JUMP
                    if best is None or score < best[0]:
                        best = (score, nm, price, sid, loc, reach[sid].jumps)
        if not best:
            return None
        _, nm, price, sid, loc, jumps = best
        st_name = con.execute("SELECT name FROM stations WHERE station_id=?", (loc,)).fetchone()
        where = st_name[0] if st_name else g.name[sid]
        return (f"STEP: BUY {qty} x {nm} FIRST ({label} for {o['agent'].split(' (')[0]}'s mission; you have none fitted)\n"
                f"   DO ONLY THIS: {'here' if jumps == 0 else f'fly {jumps} jump(s) to {g.name[sid]} and'} buy {qty} x {nm} at {where} (~{price:,.0f} ISK each; "
                f"Market > search '{nm}' > Buy), then fit them (Alt+F > drag into empty high slots).\n"
                f"   Do this BEFORE accepting: the mission's bonus clock starts when you accept. Then run  python -m eve_profit next")
    except Exception:                                                   # noqa: BLE001
        return None


def stage_text(con, g, p, o, rate_note=""):
    """The one step for the chosen agent offer `o` (a dict from agent_offers.json)."""
    agent = o["agent"].split(" (")[0]
    gear = gear_step(con, g, p, o)
    if gear:
        return gear
    st = _load(con)
    if not st or st.get("agent") != agent:
        st = {"agent": agent, "stage": "accept"}
        _save(con, st)
    if st["stage"] == "accept" and o.get("accepted"):                    # already accepted in the game (offer_update.py --accepted): go straight to doing it
        st["stage"] = "go"
        _save(con, st)
    title = o.get("mission", "")[:60]
    if st["stage"] == "accept":
        return "\n".join([f"STEP: ACCEPT {agent}'s MISSION (about 1 minute)",
                          f"   DO ONLY THIS: station window > Agents tab > {agent} > Start Conversation > read it > Accept.",
                          f"   Mission: {_brief(o)}",
                          f"   Pays: {o.get('isk', 0):,.0f} ISK + {o.get('bonus', 0):,.0f} bonus" + ("" if not o.get("granted") else f"   You are granted: {', '.join(o['granted'])}")])
    dest = o.get("to_system")
    here = p.current_system
    if dest and dest != here:
        try:
            r = g.route(g.id_of(here), g.id_of(dest), 60, p.avoid_yellow)
            hop = g.name[r.path[1]] if len(r.path) > 1 else dest
            return "\n".join([f"STEP: FLY to {hop}",
                              f"   DO ONLY THIS: fly to {hop} and stop there. Then run  python -m eve_profit next  (it plans again from there).",
                              f"   LATER: {agent}'s mission continues at {dest} ({r.jumps} jumps from here)"])
        except Exception:                                               # noqa: BLE001
            pass
    return "\n".join([f"STEP: DO {agent}'s MISSION - {title[:40]}",
                      f"   DO ONLY THIS: {_brief(o)}",
                      f"   Where: {o.get('where', 'the objective')}.",
                      "   When it is finished and handed in run:  python -m eve_profit done"])


def mark_shown(con, text):
    first = (text or "").split("\n", 1)[0]
    st = _load(con)
    if not st:
        return
    st["shown"] = "accept" if first.startswith("STEP: ACCEPT ") and "'s MISSION" in first else ("do" if first.startswith("STEP: DO ") and "'s MISSION" in first else None)
    _save(con, st)


def done(con):
    st = _load(con)
    if not st or not st.get("shown"):
        return None
    if st["shown"] == "accept":
        st["stage"], st["shown"] = "go", None
        _save(con, st)
        return f"OK, {st['agent']}'s mission is accepted. Run  python -m eve_profit next  for the first step of it."
    _save(con, None)
    return "OK, mission finished. Run  python -m eve_profit sync  then  next  (record the payout with  stop  or  fixlast  if it is missing)."
