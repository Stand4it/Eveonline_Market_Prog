"""`start` / `stop`: time an activity and let the game measure the ISK. Your wallet journal (same permission the tool
already has) lists every payout with its type and time, so ISK per hour needs no typing: start before you begin,
stop when you finish, and the result goes into the activity log the planner learns from."""
import calendar
import json
import time

# income that comes from DOING the activity (not from trading, transfers or refunds)
INCOME_TYPES = ("bounty_prizes", "agent_mission_reward", "agent_mission_time_bonus_reward",
                "project_discovery_reward", "corporation_reward_payout", "insurance", "ess_escrow_transfer")
SALE_WORDS = ("market", "hauling", "trade", "sell")       # runs with these words in the name also count market SALES as income


def _ts(iso):
    return calendar.timegm(time.strptime(iso.rstrip("Z"), "%Y-%m-%dT%H:%M:%S"))


def summarize_journal(entries, since_ts, until_ts=None, sales=False):
    """-> (total_isk, {ref_type: isk}) for payout types after since_ts. sales=True also counts market sales (positive market_transaction)."""
    by = {}
    types = INCOME_TYPES + (("market_transaction",) if sales else ())
    for e in entries:
        t = _ts(e["date"])
        if t < since_ts or (until_ts and t > until_ts):
            continue
        if e.get("ref_type") in types and e.get("amount", 0) > 0:
            by[e["ref_type"]] = by.get(e["ref_type"], 0.0) + e["amount"]
    return sum(by.values()), by


def _clock(t):
    """Local date and time of a timestamp, e.g. '2026-10-09 03:17 (local PC time)'."""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) + " (local PC time)"


def start(con, activity, char_id, now=None, snap=None, wallet=None):
    now = now or time.time()
    con.execute("INSERT OR REPLACE INTO meta VALUES('session', ?)",
                (json.dumps({"activity": activity, "t": now, "char": char_id, "snap": snap, "wallet0": wallet}),))
    try:
        n = int((con.execute("SELECT value FROM meta WHERE key='start_count'").fetchone() or ["0"])[0]) + 1
        con.execute("INSERT OR REPLACE INTO meta VALUES('start_count',?)", (str(n),))
        if activity.lower().startswith("test"):                 # you took the model-building turn: reset the clock and acknowledge new unlocks
            con.execute("INSERT OR REPLACE INTO meta VALUES('last_exp',?)", (str(n),))
            from .catalog import status
            ids = sorted(a["id"] for a in status(con, wallet or 0.0) if a["unlocked"])
            con.execute("INSERT OR REPLACE INTO meta VALUES('seen_unlocked',?)", (json.dumps(ids),))
    except Exception:                                            # noqa: BLE001
        pass
    con.commit()
    return (f"Started {_clock(now)}: timing '{activity}'. Do the activity, then run:  python -m eve_profit stop   "
            f"(add --isk N for loot you sell yourself; fell asleep or left? use --minutes N for the minutes you really worked)")


def stop(con, esi, extra_isk=0.0, now=None, paused_min=0.0, ship=None, loot=None, work_min=None, wallet_now=None):
    row = con.execute("SELECT value FROM meta WHERE key='session'").fetchone()
    if not row:
        raise ValueError("no session running: start one with  start --activity \"NAME\"")
    s = json.loads(row[0])
    now = now or time.time()
    entries = esi.paged(f"/characters/{s['char']}/wallet/journal/")
    isk, by = summarize_journal(entries, s["t"], now, sales=any(w in s["activity"].lower() for w in SALE_WORDS))
    isk += extra_isk
    total_paused = paused_min + s.get("paused_min", 0.0) + ((now - s["pause_t"]) / 60.0 if s.get("pause_t") else 0.0)   # pauses made with `pause`/`resume` + --paused
    clock_min = (now - s["t"]) / 60.0
    hours = max((now - s["t"]) / 3600.0 - total_paused / 60.0, 1 / 60.0)
    if work_min:
        hours = max(work_min / 60.0, 1 / 60.0)                    # you told us how long you really worked (asleep, away, AFK)
    if loot:
        isk += loot["value"]
        hours += loot["travel_hours"]
    sp = con.execute("SELECT SUM(sp) FROM character_skills").fetchone()[0] or None
    con.execute("INSERT INTO activity_log(activity,isk,hours,ts,ship,sp) VALUES(?,?,?,?,?,?)",
                (s["activity"], isk, hours, now, ship, sp))
    con.execute("DELETE FROM meta WHERE key='session'")
    con.commit()
    lines = [f"'{s['activity']}': {isk:,.0f} ISK in {hours * 60:.0f} min = {isk / hours:,.0f} ISK/hr (logged).",
             f"   started {_clock(s['t'])}, stopped {_clock(now)}: {clock_min:,.0f} min on the clock, {hours * 60:,.0f} min counted"
             + (" (your --minutes)" if work_min else "")]
    lines += [f"   {k:<34} {v:>14,.0f}" for k, v in sorted(by.items(), key=lambda kv: -kv[1])]
    if loot:
        from .loot import describe
        lines += describe(loot)
    if extra_isk:
        lines.append(f"   {'(your --isk for loot/salvage)':<34} {extra_isk:>14,.0f}")
    if not by and not extra_isk:
        lines.append("   No payouts found in the wallet journal for that time (ESI journal can lag a few minutes: wait and run `stop` again is NOT possible, "
                     "so use  log --activity NAME --isk N --hours H  to enter it by hand).")
    w0 = s.get("wallet0")
    if w0 is not None and wallet_now is not None:
        d = wallet_now - w0
        lines.append(f"   Your wallet changed by {d:+,.0f} ISK during this run (all income AND spending, not only this activity).")
        if d > 0 and isk <= 0:
            lines.append(f"   The journal showed nothing yet (ESI lags): if this run earned it, enter it with  fixlast --isk {d:,.0f}")
    lines.append("After 3 logged runs of the same activity the planner uses your real ISK/hr instead of its guess.")
    return "\n".join(lines)


def summary(con):
    """Every activity you have timed: runs, ISK/hr overall and per ship, so levels and hulls are never mixed up."""
    rows = con.execute("SELECT activity, COALESCE(ship,'?') AS ship, COUNT(*) n, SUM(isk) isk, SUM(hours) h "
                       "FROM activity_log GROUP BY activity, ship ORDER BY activity, ship").fetchall()
    if not rows:
        return ("Nothing timed yet. Use  start --activity \"Level 1 security mission\"  ...  stop  "
                "(name each agent level and career separately, e.g. \"Soldier of Fortune L1\", \"Level 2 security mission\").")
    L = [f"{'activity':<38} {'ship':<14} {'runs':>4} {'ISK/hr':>14} {'total ISK':>14} {'hours':>7}"]
    for r in rows:
        L.append(f"{r['activity']:<38} {r['ship']:<14} {r['n']:>4} {r['isk'] / max(r['h'], 1e-9):>14,.0f} {r['isk']:>14,.0f} {r['h']:>7.1f}")
    L.append("The planner uses the real ISK/hr once an activity name has 3 runs (names must match its activity list to be used).")
    return "\n".join(L)


def _load(con):
    row = con.execute("SELECT value FROM meta WHERE key='session'").fetchone()
    if not row:
        raise ValueError("no session running: start one with  start --activity \"NAME\"")
    return json.loads(row[0])


def _save(con, s):
    con.execute("INSERT OR REPLACE INTO meta VALUES('session', ?)", (json.dumps(s),))
    con.commit()


def pause(con, now=None):
    """Freeze the running timer (needs no login): the time until `resume` is not counted."""
    s = _load(con)
    if s.get("pause_t"):
        return f"'{s['activity']}' is already paused. Run  python -m eve_profit resume  when you are back."
    s["pause_t"] = now or time.time()
    _save(con, s)
    return f"PAUSED '{s['activity']}'. The clock is stopped. Run  python -m eve_profit resume  when you are back in game."


def resume(con, now=None):
    s = _load(con)
    if not s.get("pause_t"):
        return f"'{s['activity']}' is not paused (timer is running)."
    gone = ((now or time.time()) - s.pop("pause_t")) / 60.0
    s["paused_min"] = s.get("paused_min", 0.0) + gone
    _save(con, s)
    return f"RESUMED '{s['activity']}'. Paused {gone:.0f} min this time ({s['paused_min']:.0f} min in total, not counted). Finish, then run  python -m eve_profit stop"


def fix_last(con, add_min=0.0, add_isk=0.0, activity="", delete=False):
    """Correct the most recent timed run (or the most recent whose name contains `activity`), e.g. the minutes you worked
    while the timer was paused, or the ISK a run missed because the wallet journal had not updated yet."""
    if activity:
        r = con.execute("SELECT id,activity,isk,hours FROM activity_log WHERE activity LIKE ? ORDER BY ts DESC, id DESC LIMIT 1",
                        (f"%{activity}%",)).fetchone()
    else:
        r = con.execute("SELECT id,activity,isk,hours FROM activity_log ORDER BY ts DESC, id DESC LIMIT 1").fetchone()
    if not r:
        raise ValueError("no timed run saved yet" if not activity else f"no timed run with '{activity}' in its name")
    if delete:
        con.execute("DELETE FROM activity_log WHERE id=?", (r["id"],))
        con.commit()
        return f"Deleted the run '{r['activity']}' ({r['isk']:,.0f} ISK in {r['hours'] * 60:.0f} min)."
    isk, hours = r["isk"] + add_isk, r["hours"] + add_min / 60.0
    con.execute("UPDATE activity_log SET isk=?, hours=? WHERE id=?", (isk, hours, r["id"]))
    con.commit()
    return (f"Updated '{r['activity']}': {isk:,.0f} ISK in {hours * 60:.0f} min = {isk / max(hours, 1e-9):,.0f} ISK/hr "
            f"(was {r['isk']:,.0f} ISK in {r['hours'] * 60:.0f} min).")
