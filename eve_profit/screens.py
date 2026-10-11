"""UPDATE THE MODEL FROM THE GAME: some things the tool cannot read from ESI (AIR goals and their time limits, what an agent offers and pays, new mission
text). It lives on screenshots, and every screenshot makes later steps better: it is a step in `next` (about 3 minutes, every 12 hours) valued like
progress. `python -m eve_profit done` marks it finished."""
import json
import os
import time

KEY = "screens_ts"
EVERY_H = 12.0
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
            if o.get("available", True) and n and not n.startswith("BOTH") and n not in seen:
                seen.add(n)
                out.append(n.split(" (")[0])
        return out
    except (OSError, ValueError):
        return []


def rate():
    """When it is due it comes FIRST (it takes 3 minutes and every later step depends on the data): bigger than any hauling or trading rate."""
    return 1e8


def step():
    L = [f"STEP: UPDATE THE MODEL FROM THE GAME (about {MINUTES:.0f} minutes; it makes future ISK)",
         "   DO ONLY THIS: open these windows in game and send me a screenshot of each, one message per screenshot or all together:",
         "      1. the AIR benefits / rewards window: goals, progress, time limits, anything with a Claim button (claim it)"]
    ag = _agents()
    if ag:
        L.append(f"      2. each agent window with an open offer ({', '.join(ag[:6])}): the mission text, the rewards and the time limit")
    L.append("      3. anything new since last time (a skill queue, a new agent, planets, the market for something you hold)")
    L.append("   When they are sent run:  python -m eve_profit done")
    return "\n".join(L)
