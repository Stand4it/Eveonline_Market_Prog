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


def stage_text(con, g, p, o, rate_note=""):
    """The one step for the chosen agent offer `o` (a dict from agent_offers.json)."""
    agent = o["agent"].split(" (")[0]
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
