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
