"""`start` / `stop`: time an activity and let the game measure the ISK. Your wallet journal (same permission the tool
already has) lists every payout with its type and time, so ISK per hour needs no typing: start before you begin,
stop when you finish, and the result goes into the activity log the planner learns from."""
import calendar
import json
import time

# income that comes from DOING the activity (not from trading, transfers or refunds)
INCOME_TYPES = ("bounty_prizes", "agent_mission_reward", "agent_mission_time_bonus_reward",
                "project_discovery_reward", "corporation_reward_payout", "insurance", "ess_escrow_transfer")


def _ts(iso):
    return calendar.timegm(time.strptime(iso.rstrip("Z"), "%Y-%m-%dT%H:%M:%S"))


def summarize_journal(entries, since_ts, until_ts=None):
    """-> (total_isk, {ref_type: isk}) for payout types after since_ts."""
    by = {}
    for e in entries:
        t = _ts(e["date"])
        if t < since_ts or (until_ts and t > until_ts):
            continue
        if e.get("ref_type") in INCOME_TYPES and e.get("amount", 0) > 0:
            by[e["ref_type"]] = by.get(e["ref_type"], 0.0) + e["amount"]
    return sum(by.values()), by


def start(con, activity, char_id, now=None):
    now = now or time.time()
    con.execute("INSERT OR REPLACE INTO meta VALUES('session', ?)",
                (json.dumps({"activity": activity, "t": now, "char": char_id}),))
    con.commit()
    return f"Started timing '{activity}'. Do the activity, then run:  python -m eve_profit stop   (add --isk N for loot you sell yourself)"


def stop(con, esi, extra_isk=0.0, now=None, paused_min=0.0):
    row = con.execute("SELECT value FROM meta WHERE key='session'").fetchone()
    if not row:
        raise ValueError("no session running: start one with  start --activity \"NAME\"")
    s = json.loads(row[0])
    now = now or time.time()
    entries = esi.paged(f"/characters/{s['char']}/wallet/journal/")
    isk, by = summarize_journal(entries, s["t"], now)
    isk += extra_isk
    hours = max((now - s["t"]) / 3600.0 - paused_min / 60.0, 1 / 60.0)
    con.execute("INSERT INTO activity_log(activity,isk,hours,ts) VALUES(?,?,?,?)", (s["activity"], isk, hours, now))
    con.execute("DELETE FROM meta WHERE key='session'")
    con.commit()
    lines = [f"'{s['activity']}': {isk:,.0f} ISK in {hours * 60:.0f} min = {isk / hours:,.0f} ISK/hr (logged)."]
    lines += [f"   {k:<34} {v:>14,.0f}" for k, v in sorted(by.items(), key=lambda kv: -kv[1])]
    if extra_isk:
        lines.append(f"   {'(your --isk for loot/salvage)':<34} {extra_isk:>14,.0f}")
    if not by and not extra_isk:
        lines.append("   No payouts found in the wallet journal for that time (ESI journal can lag a few minutes: wait and run `stop` again is NOT possible, "
                     "so use  log --activity NAME --isk N --hours H  to enter it by hand).")
    lines.append("After 3 logged runs of the same activity the planner uses your real ISK/hr instead of its guess.")
    return "\n".join(lines)
