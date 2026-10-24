"""The game's notification feed (stored at every sync, character.py) as short readable lines, and a one-line notice in `next` while there are
new ones you have not looked at (owner 2026-10-23: no need to screenshot the Notification History).
python -m eve_profit.notices          show the new ones and mark them seen      (--all: the last 30)"""
import json
import re
import sys

KEY = "notices_seen"
SKIP = {"CorpAppInvitedMsg"}                                            # noise
LABEL = {
    "NPCStandingsLost": "Standing DECREASED", "NPCStandingsGained": "Standing increased",
    "MissionOfferExpirationMsg": "Mission offer EXPIRED", "MissionTimeoutMsg": "Mission TIMED OUT (failed)",
    "KillReportVictim": "SHIP LOST", "KillReportFinalBlow": "Kill (final blow)", "InsurancePayoutMsg": "Insurance paid",
    "CloneActivationMsg2": "Clone activated (you were podded)", "SkillTrainingComplete": "Skill trained",
    "ContractRequest": "Contract", "BountyClaimMsg": "Bounty paid", "AgentRetiresMsg": "AGENT RETIRED",
}


def _num(text, key):
    m = re.search(rf"{key}:\s*(-?[\d.]+)", text or "")
    return float(m.group(1)) if m else None


def _line(con, ntype, ts, text):
    lab = LABEL.get(ntype, ntype)
    extra = ""
    sys_id = _num(text, "dungeonSolarSystemID") or _num(text, "solarSystemID")
    if sys_id:
        r = con.execute("SELECT name FROM systems WHERE system_id=?", (int(sys_id),)).fetchone()
        extra += f" in {r[0]}" if r else ""
    reward = _num(text, "rewardQuantity")
    if reward:
        extra += f" (reward {reward:,.0f} ISK)"
    amount = _num(text, "amount") or _num(text, "payout")
    if amount and ntype == "InsurancePayoutMsg":
        extra += f": {amount:,.0f} ISK"
    if ntype.startswith("NPCStandings"):                               # first entry = the agent: [from_id, you, change, -1, 1, change as the game shows it]
        m = re.match(r"\s*-\s*-\s*(\d+)\s*\n\s*-\s*\d+\s*\n\s*-\s*(-?[\d.e-]+)(?:\s*\n\s*-\s*-?[\d.]+){2}(?:\s*\n\s*-\s*(-?[\d.e-]+))?", text or "")
        if m:
            who = con.execute("SELECT name FROM agent_names WHERE agent_id=?", (int(m.group(1)),)).fetchone()
            shown = abs(float(m.group(2))) * 10.0 * (-1 if ntype.endswith("Lost") else 1)   # the game shows 10x the raw change (Veirainen -0.0812 -> -0.812)
            n_other = max((text or "").count("- - ") - 1, 0)
            extra += f": {who[0] if who else 'agent ' + m.group(1)} {shown:+.3f}" + (f" ({n_other} other standings affected)" if n_other else "")
    return f"   {ts[:16].replace('T', ' ')}  {lab}{extra}"


def _seen(con):
    try:
        r = con.execute("SELECT value FROM meta WHERE key=?", (KEY,)).fetchone()
        return int(r[0]) if r else 0
    except Exception:                                                   # noqa: BLE001
        return 0


def new_rows(con):
    try:
        return con.execute("SELECT notification_id, type, ts, text FROM notifications WHERE notification_id>? ORDER BY ts",
                           (_seen(con),)).fetchall()
    except Exception:                                                   # noqa: BLE001
        return []


def notice(con):
    """One line for `next` while there are unseen notifications that matter, else ''."""
    rows = [r for r in new_rows(con) if r[1] not in SKIP]
    if not rows:
        return ""
    kinds = {}
    for r in rows:
        kinds[LABEL.get(r[1], r[1])] = kinds.get(LABEL.get(r[1], r[1]), 0) + 1
    return "GAME NOTIFICATIONS: " + "; ".join(f"{n} x {k}" for k, n in kinds.items()) + ".  Read:  python -m eve_profit.notices"


def show(con, all_=False):
    rows = con.execute("SELECT notification_id, type, ts, text FROM notifications ORDER BY ts DESC LIMIT 30").fetchall()[::-1] if all_ else new_rows(con)
    rows = [r for r in rows if r[1] not in SKIP]
    if not rows:
        return "No new game notifications."
    top = max(r[0] for r in rows)
    con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (KEY, str(max(top, _seen(con)))))
    con.commit()
    return "\n".join(["GAME NOTIFICATIONS (from the last sync):"] + [_line(con, r[1], r[2], r[3]) for r in rows])


if __name__ == "__main__":
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from eve_profit.db import connect
    print(show(connect(os.environ.get("EVE_PROFIT_DB") or "E:/EveProfit/eve_profit_dahl.db"), "--all" in sys.argv))
