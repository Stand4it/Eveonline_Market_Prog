"""What changed in your wallet since the last sync, split by what the game says paid or charged it (journal ref types: market sales, AIR Career Program
Reward, Daily Goal Reward, taxes, fees...). The balance is live; the ESI journal can lag up to an hour, so the part it does not explain yet is shown as such."""
import calendar
import json
import time


def _ts(s):
    try:
        return float(calendar.timegm(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")))
    except Exception:                                                   # noqa: BLE001
        return 0.0


NICE = {"air_career_program_reward": "AIR Career Program Reward", "daily_goal_payouts": "Daily Goal Reward", "market_transaction": "market sales / purchases",
        "transaction_tax": "sales tax", "brokers_fee": "broker fees", "market_escrow": "market escrow", "bounty_prizes": "bounties", "agent_mission_reward": "mission reward",
        "agent_mission_time_bonus_reward": "mission time bonus", "player_donation": "ISK given/received"}


def report(con, esi, cid, wallet_now):
    try:
        r = con.execute("SELECT value FROM meta WHERE key='wallet_last'").fetchone()
        last = json.loads(r[0]) if r else None
        con.execute("INSERT OR REPLACE INTO meta VALUES('wallet_last', ?)", (json.dumps({"isk": wallet_now, "t": time.time()}),))
        con.commit()
    except Exception:                                                   # noqa: BLE001
        return ""
    if not last:
        return ""
    delta = wallet_now - last["isk"]
    late = _late_report(con, esi, cid)                                  # an earlier gap the journal may explain by now
    if abs(delta) < 1:
        return "WALLET since last sync: no change." + (("\n" + late) if late else "")
    try:
        rows = esi.get(f"/characters/{cid}/wallet/journal/")[0]
    except Exception:                                                   # noqa: BLE001
        rows = []
    by, explained = {}, 0.0
    for e in rows:
        if _ts(e.get("date", "")) > last["t"] - 5 and abs(e.get("amount", 0)) > 0:           # only entries newer than the last sync
            k = NICE.get(e.get("ref_type", ""), e.get("ref_type", "other"))
            by[k] = by.get(k, 0.0) + e["amount"]
            explained += e["amount"]
    L = [f"WALLET since last sync: {delta:+,.0f} ISK (balance {wallet_now:,.0f})"]
    for k, v in sorted(by.items(), key=lambda kv: -abs(kv[1])):
        L.append(f"   {v:+12,.0f}  {k}")
    gap = delta - explained
    if abs(gap) >= 1:
        L.append(f"   {gap:+12,.0f}  not in the journal yet (ESI lags up to an hour: AIR / daily goal rewards and sales often show late)")
        try:                                                            # remember it: a later sync reports what the journal says about it
            con.execute("INSERT OR REPLACE INTO meta VALUES('wallet_pending', ?)", (json.dumps({"t": last["t"], "gap": gap, "made": time.time()}),))
            con.commit()
        except Exception:                                               # noqa: BLE001
            pass
    if late:
        L.append(late)
    return "\n".join(L)


def _late_report(con, esi, cid):
    """A gap from an earlier sync: once the journal has entries since then, list them (and forget the gap); give up after 3 hours. -> text or ''."""
    try:
        r = con.execute("SELECT value FROM meta WHERE key='wallet_pending'").fetchone()
        pend = json.loads(r[0]) if r else None
    except Exception:                                                   # noqa: BLE001
        return ""
    if not pend:
        return ""
    if time.time() - pend["made"] > 3 * 3600:
        con.execute("DELETE FROM meta WHERE key='wallet_pending'")
        con.commit()
        return ""
    try:
        rows = esi.get(f"/characters/{cid}/wallet/journal/")[0]
    except Exception:                                                   # noqa: BLE001
        return ""
    by, tot = {}, 0.0
    for e in rows:
        if _ts(e.get("date", "")) > pend["t"] - 5 and abs(e.get("amount", 0)) > 0:
            k = NICE.get(e.get("ref_type", ""), e.get("ref_type", "other"))
            by[k] = by.get(k, 0.0) + e["amount"]
            tot += e["amount"]
    if not by:
        return ""
    L = [f"THE JOURNAL NOW EXPLAINS THE EARLIER GAP ({pend['gap']:+,.0f} ISK unexplained at the last sync):"]
    for k, v in sorted(by.items(), key=lambda kv: -abs(kv[1])):
        L.append(f"   {v:+12,.0f}  {k}")
    if abs(tot - pend["gap"]) < 1 or tot >= pend["gap"]:
        con.execute("DELETE FROM meta WHERE key='wallet_pending'")
        con.commit()
    return "\n".join(L)
