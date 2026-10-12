"""UPDATE THE MODEL FROM THE GAME: some things the tool cannot read from ESI (AIR goals and their time limits, what an agent offers and pays, new mission
text). It lives on screenshots, and every screenshot makes later steps better: it is a step in `next` (about 3 minutes, every 12 hours) valued like
progress. `python -m eve_profit done` marks it finished."""
import json
import os
import time

KEY = "screens_ts"
EVERY_H = 72.0          # the agent windows were all recorded: ask again only every 3 days
MINUTES = 3.0
VALUE_ISK = 60_000.0          # what the step is worth: the data it brings makes every later step better (editable here)


def due(con):
    try:
        r = con.execute("SELECT value FROM meta WHERE key=?", (KEY,)).fetchone()
        return not r or (time.time() - float(r[0])) / 3600.0 >= EVERY_H
    except Exception:                                                   # noqa: BLE001
        return True


def mark(con):
    con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (KEY, str(time.time())))
    con.commit()


def _agents():
    f = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent_offers.json")
    try:
        d = json.load(open(f, encoding="utf-8"))
        seen, out = set(), []
        for o in d.get("offers", []):
            n = o.get("agent", "")
            if o.get("available", True) and o.get("agent_system", "Rotonos") == "Rotonos" and n and not n.startswith("BOTH") and n not in seen:
                seen.add(n)
                out.append(n.split(" (")[0])
        return out
    except (OSError, ValueError):
        return []


def rate():
    """When it is due it comes FIRST (it takes 3 minutes and every later step depends on the data): bigger than any hauling or trading rate."""
    return 6e6                                  # below the one-minute AIR goals (about 7M/hr): quick high-value steps first


IDX_KEY = "screens_idx"


def items():
    """The screens to send, one per step: the AIR benefits window, then each agent window with an open offer."""
    out = [("the AIR benefits / rewards window (claim anything with a Claim button)", "goals, progress, time limits")]
    out.append(("the Agency window > Agents & Missions > Mission Agents (left-side Agency button), sorted by distance",
                "the list of agents: name, level, corporation, jumps away, standing needed (tip: use the Filters on the left: Level, Location, Security, Faction)"))
    out.append(("the Agency window > Agents & Missions > Epic Arcs",
                "the arcs offered, their start system and how many jumps away"))
    out += [(f"{a}'s agent window (Start Conversation, so the current mission shows)", "the whole mission window: step title and number, objectives, rewards, bonus reward and its time limit, the agent's standing with you") for a in _agents()[:8]]
    return out


def _idx(con):
    try:
        r = con.execute("SELECT value FROM meta WHERE key=?", (IDX_KEY,)).fetchone()
        return int(r[0]) if r else 0
    except Exception:                                                   # noqa: BLE001
        return 0


def advance(con):
    """`done`: the screen shown was sent. Move to the next one; after the last, the whole step is finished for 12 hours. -> text."""
    its = items()
    i = _idx(con) + 1
    if i >= len(its):
        con.execute("DELETE FROM meta WHERE key=?", (IDX_KEY,))
        mark(con)
        return "All the screens are sent. Thank you: the model is updated for the next 12 hours."
    con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (IDX_KEY, str(i)))
    con.commit()
    return f"Screen {i} of {len(its)} sent. Run  python -m eve_profit next  for the next one."


def step(con=None):
    """ONE screen at a time."""
    its = items()
    i = min(_idx(con) if con is not None else 0, len(its) - 1)
    what, show = its[i]
    return "\n".join([f"STEP: UPDATE THE MODEL FROM THE GAME - screen {i + 1} of {len(its)} (about 30 seconds)",
                      f"   DO ONLY THIS: open {what}",
                      f"   Show me: {show}.",
                      "   To send it: press  Win + Shift + S , drag a box around the window, then press  Ctrl + V  in the chat with me.",
                      "   When it is sent run:  python -m eve_profit done"])


def goto(con, n):
    """`done --screen N`: several screens were sent at once; show screen N next."""
    its = items()
    if n > len(its):                                                    # past the end = skip the whole step for now
        con.execute("DELETE FROM meta WHERE key=?", (IDX_KEY,))
        mark(con)
        return "OK, the game-screens step is skipped until it is due again."
    i = max(0, min(n - 1, len(its) - 1))
    con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (IDX_KEY, str(i)))
    con.commit()
    return f"OK. Next to send: screen {i + 1} of {len(its)}. Run  python -m eve_profit next"


WANTED_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "screens_wanted.json")
SEEN_KEY, SHOWN_KEY = "wanted_seen", "wanted_shown"
WANTED_RATE = 8_000_000.0      # a one-time 1-minute request: asked soon, but a social goal or a real mission still comes first


def _meta(con, key, default=None):
    try:
        r = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r[0] if r else default
    except Exception:                                                   # noqa: BLE001
        return default


def _state(con):
    try:
        st = json.loads(_meta(con, "wanted_state", "{}"))
    except ValueError:
        st = {}
    for i in json.loads(_meta(con, SEEN_KEY, "[]")):                    # older one-time record
        st.setdefault(i, {"ts": 0.0, "int": 0, "n": 1, "chg": 0, "legacy": True})
    return st


def _moved(con, item, g, p):
    """A list that shows what is near YOU is due again once you are `jumps` away from where it was last scanned."""
    mv = item.get("moves")
    if not mv or g is None or p is None:
        return False
    try:
        from .listings import origin_of
        o = origin_of(con, mv["list"])
        return bool(o) and o != p.current_system and g.route(g.id_of(o), g.id_of(p.current_system), 60, p.avoid_yellow).jumps >= mv["jumps"]
    except Exception:                                                   # noqa: BLE001
        return False


def _dynamic():
    """Detail pages the data itself says are missing (freelance_jobs.json: jobs marked unverified)."""
    out = []
    try:
        jobs = json.load(open(os.path.join(os.path.dirname(WANTED_FILE), "freelance_jobs.json"), encoding="utf-8")).get("mining_jobs", [])
    except (OSError, ValueError):
        return out
    for j in jobs:
        if j.get("unverified"):
            out.append({"id": "jobdetail_" + j["ore"].lower(), "where": f"Freelance Jobs > click the job '{j.get('title', 'Mine ' + j['ore'])}'",
                        "show": "the whole detail page: reward per unit mined, your cap, expiry, eligible locations, number of participants",
                        "why": f"the {j['ore']} job's pay per unit is only assumed ({j['isk_per_unit']:.2f} ISK) until the page is seen"})
    return out


def wanted_unseen(con, g=None, p=None):
    """The screens that are due: never sent, or a repeating one whose (adaptive) interval has passed."""
    try:
        items = json.load(open(WANTED_FILE, encoding="utf-8")).get("items", []) + _dynamic()
    except (OSError, ValueError):
        return []
    st, now, out = _state(con), time.time(), []
    for i in items:
        s_ = st.get(i["id"])
        if not s_ or (i.get("repeat") and not s_.get("legacy") and now - s_["ts"] >= s_["int"] * 3600.0) or _moved(con, i, g, p):
            out.append(i)
    return out


def wanted_candidate(con, g=None, p=None):
    """(rate, step text) for the next screenshot the model needs, or None."""
    left = wanted_unseen(con, g, p)
    if not left:
        return None
    i = left[0]
    text = "\n".join([f"STEP: SHOW ME A SCREEN - {i['where'].split(' > ')[0]} (about 1 minute)",
                      f"   DO ONLY THIS: open  {i['where']}",
                      f"   Show me: {i['show']}.",
                      f"   Why: {i['why']}.",
                      "   To send it: press  Win + Shift + S , drag a box around the window, then press  Ctrl + V  in the chat with me.",
                      ("   When it is sent run:  python -m eve_profit done --changed   (it looks different from last time)   or   python -m eve_profit done --same"
                       if (i.get("repeat") and not i.get("auto")) else "   When it is sent run:  python -m eve_profit done")])
    return WANTED_RATE, text


def wanted_mark_shown(con, text, g=None, p=None):
    if (text or "").startswith("STEP: SHOW ME A SCREEN"):
        for i in wanted_unseen(con, g, p):
            if f"open  {i['where']}" in text:
                con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (SHOWN_KEY, i["id"]))
                con.commit()
                return


def wanted_done(con, changed=None):
    """`done` [--changed | --same]: the shown screen was sent. A repeating screen's interval adapts: changed -> half as long (not below min_h),
    same -> 1.5x as long (not above max_h). -> message or None."""
    wid = _meta(con, SHOWN_KEY)
    if not wid:
        return None
    try:
        item = next(i for i in json.load(open(WANTED_FILE, encoding="utf-8"))["items"] + _dynamic() if i["id"] == wid)
    except (OSError, ValueError, StopIteration, KeyError):
        item = {"id": wid}
    st = _state(con)
    old = st.get(wid) or {"int": item.get("base_h", 0), "n": 0, "chg": 0}
    n, chg, iv = old["n"] + 1, old["chg"] + (1 if changed else 0), old["int"] or item.get("base_h", 0)
    if item.get("repeat"):
        lo, hi = item.get("min_h", 6), item.get("max_h", 168)
        if changed is True:
            iv = max(lo, iv / 2.0)
        elif changed is False:
            iv = min(hi, iv * 1.5)
    st[wid] = {"ts": time.time(), "int": iv, "n": n, "chg": chg}
    con.execute("INSERT OR REPLACE INTO meta VALUES('wanted_state',?)", (json.dumps(st),))
    con.execute("DELETE FROM meta WHERE key=?", (SHOWN_KEY,))
    con.commit()
    more = f" This one comes back in about {iv:.0f} h." if item.get("repeat") else ""
    return f"Thank you.{more} {len(wanted_unseen(con))} more screen(s) wanted. Run  python -m eve_profit next"
