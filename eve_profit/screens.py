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
            if o.get("available", True) and o.get("agent_system", "Rotonos") == "Rotonos" and n and not n.startswith("BOTH") and n not in seen:
                seen.add(n)
                out.append(n.split(" (")[0])
        return out
    except (OSError, ValueError):
        return []


def rate():
    """When it is due it comes FIRST (it takes 3 minutes and every later step depends on the data): bigger than any hauling or trading rate."""
    return 1e8


IDX_KEY = "screens_idx"


def items():
    """The screens to send, one per step: the AIR benefits window, then each agent window with an open offer."""
    out = [("the AIR benefits / rewards window (claim anything with a Claim button)", "goals, progress, time limits")]
    out.append(("the Agency window > Agents & Missions > Mission Agents (left-side Agency button), sorted by distance",
                "the list of agents: name, level, corporation, jumps away, standing needed (tip: use the Filters on the left: Level, Location, Security, Faction)"))
    out.append(("the Agency window > Agents & Missions > Epic Arcs",
                "the arcs offered, their start system and how many jumps away"))
    out += [(f"{a}'s agent window", "the mission text, the rewards and the time limit") for a in _agents()[:8]]
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
    i = max(0, min(n - 1, len(its) - 1))
    con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (IDX_KEY, str(i)))
    con.commit()
    return f"OK. Next to send: screen {i + 1} of {len(its)}. Run  python -m eve_profit next"
