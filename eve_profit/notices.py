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
            shown = float(m.group(2)) * 10.0                            # the game shows 10x the raw change; its SIGN is the truth: CCP types gains as
            lab = "Standing increased" if shown > 0 else "Standing DECREASED"   # 'NPCStandingsLost' too (2026-10-25: two completed missions showed as losses)
            n_other = max((text or "").count("- - ") - 1, 0)
            extra += f": {who[0] if who else 'agent ' + m.group(1)} {shown:+.3f}" + (f" ({n_other} other standings affected)" if n_other else "")
    return f"   {ts[:16].replace('T', ' ')}  {lab}{extra}"


OFFER_DAYS = 7


def expire_offers(con):
    """Mark recorded offers that the game says EXPIRED as gone (available=false), so `next` stops planning them. A notice matches an open,
    not-accepted offer with the same cash reward whose pickup/drop-off system is one of the notice's systems (or that has none recorded),
    recorded on or before that day. -> names of the offers closed."""
    import os
    import sys as _sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _sys.path.insert(0, os.path.join(root, "scripts"))
    from offers_lock import offers_lock
    rows = con.execute("SELECT ts, text FROM notifications WHERE type='MissionOfferExpirationMsg'").fetchall()
    names = {r[0]: r[1] for r in con.execute("SELECT system_id, name FROM systems")}
    path = os.path.join(root, "agent_offers.json")
    closed = []
    with offers_lock():
        d = json.load(open(path, encoding="utf-8"))
        for ts, text in rows:
            reward = _num(text, "rewardQuantity")
            if not reward:
                continue
            systems = {names.get(int(v)) for k in ("objectiveLocationSystemID", "objectiveDestinationSystemID", "dungeonSolarSystemID")
                       for v in [_num(text, k)] if v} - {None}
            day = (ts or "")[:10]
            for o in d["offers"]:
                if not o.get("available", True) or o.get("accepted") or int(o.get("isk", -1)) != int(reward):
                    continue
                osys = {o.get("agent_system"), o.get("to_system")} - {None, ""}
                seen = re.search(r"Seen (\d{4}-\d{2}-\d{2})", o.get("note", "") or "")
                if systems and osys and not (systems & osys):
                    continue
                if seen and seen.group(1) > day:
                    continue                                            # a newer offer from the same agent: not this one
                o["available"] = False
                o["note"] = (o.get("note", "") + f" EXPIRED {day} (game notice).").strip()
                closed.append(o["agent"].split(" (")[0])
                break
        import datetime as _dt                                          # game notices (22 of them, 2026-10-28) show an unaccepted offer lives 7 days
        cutoff = (_dt.date.today() - _dt.timedelta(days=OFFER_DAYS)).isoformat()   # from when it was offered; Seen is on or after that, so this is safe
        for o in d["offers"]:
            seen = re.search(r"Seen (\d{4}-\d{2}-\d{2})", o.get("note", "") or "")
            if o.get("available", True) and not o.get("accepted") and seen and seen.group(1) <= cutoff:
                o["available"] = False
                o["note"] = (o.get("note", "") + f" EXPIRED (seen {seen.group(1)}, offers last {OFFER_DAYS} days).").strip()
                closed.append(o["agent"].split(" (")[0])
        if closed:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                json.dump(d, f, indent=1, ensure_ascii=False)
                f.write("\n")
    return closed


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
