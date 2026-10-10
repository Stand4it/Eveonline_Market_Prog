"""Bonus programs and events (bonus_programs.json): extra ISK/points for things you do anyway. Added to agent-offer values and
shown on market steps. Edit the JSON from screenshots."""
import json
import os

_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bonus_programs.json")


def programs():
    try:
        return json.load(open(_FILE, encoding="utf-8")).get("programs", [])
    except (OSError, ValueError):
        return []


def offer_bonus(career, progs=None):
    """(extra ISK, text) a program pays when this agent offer's career completes one of its missions."""
    isk, parts = 0.0, []
    for pr in progs if progs is not None else programs():
        if pr.get("kind") == "career_missions" and career in pr.get("careers", []) and pr.get("safe", True):
            isk += pr.get("reward_isk", 0)
            parts.append(f"{pr['name']}: +{pr.get('reward_isk', 0):,.0f} ISK" + (f" +{pr['career_points']} career points" if pr.get("career_points") else ""))
    return isk, "; ".join(parts)


def market_lines(progs=None):
    """Lines for sell/trade steps: open market goals this step helps with."""
    L = []
    for pr in progs if progs is not None else programs():
        if pr.get("market") and pr.get("safe", True):
            prog = pr.get("progress_isk", pr.get("progress", 0))
            tgt = pr.get("target_isk", pr.get("target", 0))
            if tgt and prog >= tgt:
                continue
            L.append(f"   bonus: counts toward '{pr['name']}' ({prog:,.0f}/{tgt:,.0f})")
    return L


def daily_goal_hits(mission_text, progs=None):
    """AIR Daily Goals an agent mission also advances (matched by words in the mission text): -> ['Scan 5 Signatures (0/5)', ...]."""
    low = mission_text.lower()
    out = []
    for pr in progs if progs is not None else programs():
        if pr.get("kind") == "daily_goals":
            for g in pr.get("goals", []):
                if any(k in low for k in g.get("keywords", [])):
                    out.append(f"{g['goal']} ({g.get('progress', '')})")
    return out


def daily_goal_program(progs=None):
    for pr in progs if progs is not None else programs():
        if pr.get("kind") == "daily_goals":
            return pr
    return None


def daily_goal_due(con, today=None):
    """True when no AIR Daily Goal reward has been seen in your wallet journal today (UTC), so the 2-of-5 daily reward is still on the table."""
    import time as _t
    today = today or _t.strftime("%Y-%m-%d", _t.gmtime())
    try:
        r = con.execute("SELECT value FROM meta WHERE key='daily_goal_last'").fetchone()
    except Exception:                                                   # noqa: BLE001
        return True
    return not (r and r[0] == today)


def daily_goal_step(pr):
    L = [f"STEP: AIR DAILY GOALS - about {pr.get('reward_isk', 0):,.0f} ISK for any 2 of the 5 goals (resets daily)"]
    for g in pr.get("goals", []):
        L.append(f"   {g['goal']:<34} {g.get('progress', '')}")
    L.append("   Cheapest pair: Complete 3 Jumps (any trip, e.g. to Manifest and back) + Manufacture an Item (start any small build in Industry),"
             " or Scan 5 Signatures. Check the Opportunities > AIR Daily Goals window.")
    return "\n".join(L)
