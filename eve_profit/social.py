"""AIR Career Program 'Social' goals (Soldier of Fortune): each pays 25,000 ISK + 10 career points for a one-minute click task (risk none). One goal per step;
`done` marks the one shown. Join a Fleet / Join a Corporation are NOT offered (a fleet needs an invite; a corporation changes your corp)."""
import json

KEY = "social_done"
SHOWN = "social_shown"
MIN_EACH = 2.0
GOALS = (
    ("Send a Message in Chat", "open a chat channel (Local, or the Corp channel at the bottom of the screen), click the text box, type  o7  and press Enter."),
    ("Add a new Contact", "right-click any other player's name (in Local chat) > Add Contact > OK."),
    ("Send an EVE Mail", "Neocom menu > EVE Mail > New Message: To = your own character, Subject = test, any text, Send."),
)


def _meta(con, key, default=None):
    try:
        r = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r[0] if r else default
    except Exception:                                                   # noqa: BLE001
        return default


def done_list(con):
    try:
        return json.loads(_meta(con, KEY, "[]"))
    except ValueError:
        return []


def pending(con):
    d = done_list(con)
    return [g for g in GOALS if g[0] not in d]


def candidate(con, value_isk):
    """(rate ISK/hr, step text) or None. value_isk = ISK-equivalent of one goal (25,000 + 10 career points)."""
    left = pending(con)
    if not left:
        return None
    name, how = left[0]
    text = "\n".join([f"STEP: AIR SOCIAL GOAL - {name} (about {MIN_EACH:.0f} minutes)",
                      f"   DO ONLY THIS: {how}",
                      "   It pays 25,000 ISK + 10 career points toward the 50,000 skill point milestone. If the AIR window shows a Claim button, press it.",
                      "   When it is done run:  python -m eve_profit done"])
    return value_isk * 60.0 / MIN_EACH, text


def mark_shown(con, text):
    first = (text or "").split("\n", 1)[0]
    if first.startswith("STEP: AIR SOCIAL GOAL - "):
        name = first[len("STEP: AIR SOCIAL GOAL - "):].split(" (about")[0]
        con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (SHOWN, name))
        con.commit()


def done(con):
    """`done`: mark the goal that was shown. -> message or None when no social goal was shown."""
    name = _meta(con, SHOWN)
    if not name:
        return None
    d = done_list(con)
    if name not in d:
        d.append(name)
    con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (KEY, json.dumps(d)))
    con.execute("DELETE FROM meta WHERE key=?", (SHOWN,))
    con.commit()
    left = len(pending(con))
    return f"OK, '{name}' is marked done. {left} social goal(s) left. Run  python -m eve_profit next"
