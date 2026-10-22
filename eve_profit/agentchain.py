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


GEAR_QTY = {"gun": 6, "mining": 2}                  # how many to fit for a mission (owner 2026-10-21: 6 guns on the Catalyst)
AMMO = ["Antimatter Charge S", "Plutonium Charge S", "Uranium Charge S", "Thorium Charge S", "Lead Charge S", "Iridium Charge S", "Tungsten Charge S", "Iron Charge S"]   # most damage first: a near-equal price picks the harder-hitting one
AMMO_NEED = 1200                                     # 200 rounds per gun for 6 guns
FITTED_KEY = "gear_fitted"


def _held_any(con, names):
    from .acquire import held
    return sum(held(con, n) for n in names)


def _cheapest(con, g, p, names, qty):
    """(name, price, system id, station id, jumps) of the cheapest place to buy `qty` within 10 jumps, a jump priced at your time (meta best_rate)."""
    import time as _t
    r = con.execute("SELECT value FROM meta WHERE key='best_rate'").fetchone()
    per_jump = 2.5 * (float(r[0]) if r and r[0] else 1_000_000.0) / 60.0
    reach = g.reach(g.id_of(p.current_system), 10, p.avoid_yellow)
    best = None
    for rank, nm in enumerate(names):
        for price, sid, loc in con.execute("SELECT o.price, o.system_id, o.location_id FROM orders o JOIN types t ON t.type_id=o.type_id WHERE t.name=? AND o.is_buy=0 "
                                           "AND o.volume_remain>=? AND o.fetched_at>?", (nm, qty, _t.time() - 2 * 86400)):
            if sid in reach:
                score = price * qty * (1 + 0.05 * rank) + reach[sid].jumps * 2 * per_jump      # names are in order of preference
                if best is None or score < best[0]:
                    best = (score, nm, price, sid, loc, reach[sid].jumps)
    return best[1:] if best else None


def _buy_or_fly(con, g, p, nm, qty, price, sid, loc, jumps, why):
    """One step: buy here, or the next hop toward the seller (route trades and boosters are added to a FLY step by `next`)."""
    st = con.execute("SELECT name FROM stations WHERE station_id=?", (loc,)).fetchone()
    where = st[0] if st else g.name[sid]
    if jumps == 0:
        return (f"STEP: BUY {qty:,} x {nm} here ({why})\n"
                f"   DO ONLY THIS: Market > search '{nm}' > Buy {qty:,} at {where} (~{price:,.0f} ISK each), then put it straight into your ship.\n"
                f"   Then:  python -m eve_profit done --goal \"bought {qty} {nm}\"")
    r = g.route(g.id_of(p.current_system), sid, 60, p.avoid_yellow)
    hop = g.name[r.path[1]] if r and len(r.path) > 1 else g.name[sid]
    return (f"STEP: FLY to {hop}\n"
            f"   WHY: to buy {qty:,} x {nm} in {g.name[sid]} ({jumps} jumps, ~{price:,.0f} ISK each at {where}): {why}\n"
            f"   DO ONLY THIS: fly to {hop} and stop there. Then run  python -m eve_profit next  (it plans again from there).")


def gear_step(con, g, p, o):
    """An offer that needs a tool you have not fitted (o['needs_tool'] = a key of tools.TOOLS): the next step that gets it, one item at a time
    (guns, then ammo for guns), each at the cheapest place counting your time; then FIT. Shown BEFORE accepting (the bonus clock starts at accept)
    or, for an accepted mission, before doing it. -> text or None (ready, unknown tool, or no seller found)."""
    nt = o.get("needs_tool")
    try:
        import json as _json
        import time as _t
        from . import tools as _tl
        if not nt or nt not in _tl.TOOLS:
            return None
        r = con.execute("SELECT value FROM meta WHERE key=?", (FITTED_KEY,)).fetchone()
        fitted_marks = _json.loads(r[0]) if r and r[0] else {}
        fitted = _tl.fitted_now(con).get(nt, 0) >= 1 or _t.time() - fitted_marks.get(nt, 0) < 3 * 3600
        item, _q = _tl.TOOLS[nt]["buy"][0]
        qty = GEAR_QTY.get(nt, _q)
        label = _tl.TOOLS[nt]["label"]
        who = o["agent"].split(" (")[0]
        why = f"{label} for {who}'s mission"
        names = CHEAP_ALT.get(nt, []) + [item]
        needs = []                                                          # (names, qty, why): what is still to buy
        have = _held_any(con, names)
        if not fitted and have < qty:
            needs.append((names, qty - have, why + "; you have none fitted"))
        if nt == "gun" and _held_any(con, AMMO) < AMMO_NEED:                 # guns need ammo: 200 rounds per gun
            needs.append((AMMO, AMMO_NEED - _held_any(con, AMMO), f"ammo for your guns ({who}'s mission)"))
        found = [(c, q, w) for n, q, w in needs for c in [_cheapest(con, g, p, n, q)] if c]
        found.sort(key=lambda x: x[0][4])                                   # whatever can be bought RIGHT HERE first, then the nearest
        if found:
            c, q, w = found[0]
            return _buy_or_fly(con, g, p, c[0], q, c[1], c[2], c[3], c[4], w)
        if not fitted:
            ship = (p.ship_name or "").split(" - ")[0] or "ship"
            return (f"STEP: FIT {qty} x {item} to your {ship} ({why})\n"
                    f"   DO ONLY THIS: Alt+F (fitting window) > drag them from cargo/hangar into empty high slots; load the ammo (right-click a gun > Reload).\n"
                    f"   Then:  python -m eve_profit done --goal \"fitted {nt}\"")
        return None
    except Exception:                                                   # noqa: BLE001
        return None


def mark_fitted(con, tool):
    import json as _json
    import time as _t
    r = con.execute("SELECT value FROM meta WHERE key=?", (FITTED_KEY,)).fetchone()
    st = _json.loads(r[0]) if r and r[0] else {}
    st[tool] = _t.time()
    con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (FITTED_KEY, _json.dumps(st)))
    con.commit()
    return f"OK, {tool} marked as fitted (the fitting data from the game can lag; this covers 3 hours)."


def accepted_candidate(con, g, p, top_rate):
    """An ACCEPTED mission is a commitment (owner 2026-10-21): its next step (gear first, then the mission) ranks above everything else
    while its bonus can still be earned. -> (rate, label, text, note) or None."""
    import json as _json
    import os as _os
    f = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "agent_offers.json")
    try:
        offers = _json.load(open(f, encoding="utf-8")).get("offers", [])
    except (OSError, ValueError):
        return None
    acc = [o for o in offers if o.get("available", True) and o.get("accepted")
           and o.get("needs_tool") != "gun"]                                 # combat is NOT forced: it waits for a fit that passes the 99% win rule
                                                                             # (2026-10-21: a Catalyst with 6 guns + 1 repairer died in 'Worlds Collide')
    if not acc:
        return None
    acc.sort(key=lambda o: -(o.get("isk", 0) + o.get("bonus", 0)))           # the richest accepted mission first
    o = acc[0]
    text = stage_text(con, g, p, o)
    return (max(top_rate, 1.0) * 1.5 + 1.0, f"accepted mission: {o['agent'].split(' (')[0]}", text, "you accepted it: finish it (gear first)")


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
    combat = o.get("needs_tool") == "gun" or "kill" in (o.get("mission", "") + o.get("needs", "")).lower()
    return "\n".join([f"STEP: DO {agent}'s MISSION - {title[:40]}"]
                     + ([f"   FIRST: dock and leave EVERYTHING you do not need for the fight in the station hangar (cargo, spare modules): "
                         f"a lost ship loses its cargo too (owner rule 2026-10-21). Keep only ammo and the mission item."] if combat else [])
                     + [f"   DO ONLY THIS: {_brief(o)}",
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
