"""`next`: ONE short instruction at a time. Priority: (1) cash in the liquid stock here, (2) list the single best
high-gap item, (3) the best trade (verify with `check`). Do the step, run `sync`, run `next` again."""
from .along import plan_along
from .planner import plan

AFTER = "Then run:  python -m eve_profit now"


def _next_action_core(con, g, p):
    res = plan_along(con, g, p, p.current_system)
    here = res["sell_here"]
    where = p.current_system
    docked = "" if p.current_location_id else f"(undocked? dock at a {where} station first)\n"
    sells = [d for d in here if d["advice"] != "LIST" and d["net"] >= 50_000]
    if sells:
        total = sum(d["net"] for d in sells)
        L = [f"STEP: SELL NOW in {where} - about {total:,.0f} ISK", docked.rstrip()]
        for d in sells[:8]:
            L.append(f"   {d['sold']:>9,} x {d['name']:<34} ~{d['net']:>12,.0f}")
        if len(sells) > 8:
            L.append(f"   ...and {len(sells) - 8} more smaller stacks (all marked SELL NOW in `along`)")
        big = sells[0]
        if big["net"] >= 5_000_000:
            L.append(f"   BIG ONE: before selling {big['name']}, compare other markets:  python -m eve_profit bestprice --item \"{big['name']}\"")
        L.append("   In game: Market > item > Sell > pick the HIGHEST buy order at your station.")
        L.append(AFTER)
        return "\n".join(x for x in L if x != "")
    listers = [d for d in here if d["advice"] == "LIST"]
    if listers:
        d = max(listers, key=lambda d: d["list_net"] - d["net"])
        ask = con.execute("SELECT price FROM orders WHERE type_id=? AND system_id=? AND is_buy=0 ORDER BY price ASC LIMIT 1",
                          (d["tid"], g.id_of(where))).fetchone()
        price = ask[0] if ask else d["listing"] / max(d["qty"], 1)
        slots = res.get("slots")
        L = [f"STEP: LIST 1 item in {where}",
             f"   {d['qty']:,} x {d['name']}",
             f"   price each: {price:,.2f}  (the cheapest sell order right now; match or undercut by the smallest step)",
             f"   you receive about {d['list_net']:,.0f} ISK after fees (instant sale would give {d['net']:,.0f})"]
        if slots is not None:
            L.append(f"   uses 1 of your ~{slots} market order slots")
        L.append("   In game: right-click the item in your hangar > Sell this item > choose 'Create sell order'.")
        L.append(AFTER)
        return "\n".join(L)
    opps = plan(con, p, 30, False)
    if opps:
        o = opps[0]
        L = [f"STEP: {o.kind.upper()} (nothing left to sell here; best of everything ranked by ISK/hr)",
             f"   {o.description}",
             f"   profit about {o.net_isk:,.0f} ISK in {o.hours * 60:.0f} min ({o.isk_per_hour:,.0f} ISK/hr)"]
        if o.kind in ("trade", "liquidate"):
            L.append("   FIRST confirm live prices:   python -m eve_profit check --pick 1")
        L.append("   then route:                  python -m eve_profit go --pick 1 --send")
        L.append(AFTER)
        return "\n".join(L)
    return "No clear action. Refresh data:  python -m eve_profit scan --live   then   python -m eve_profit next"


HOME_NOTE = ("EARLY-GAME TASK: your home station is a player-owned structure. Owners can charge docking fees and market taxes there. "
             "Move your home to a free NPC station near a trade hub: dock at an NPC station that has a Clone Bay, open the "
             "Clone Bay window and choose Set Home Station. (NPC stations charge no extra tax; you still pay the normal sales tax and broker fee.)")


AGENT_PREFIX = "Agent L1"


def agent_note(con, g, p):
    """One block about timed agent-mission runs (activity names starting 'Agent L1'): measured ISK/hr vs the best ranked opportunity."""
    try:
        rows = con.execute("SELECT activity, COUNT(*), SUM(isk), SUM(hours) FROM activity_log WHERE activity LIKE ? GROUP BY activity",
                           (AGENT_PREFIX + "%",)).fetchall()
    except Exception:                                                   # noqa: BLE001
        return ""
    rows = [r for r in rows if r[3] and r[3] > 0]
    if not rows:
        return ("AGENT MISSIONS (not measured yet): Level 1 agents often pay more than trading early on. Time one run with\n"
                "   python -m eve_profit start --activity \"Agent L1 step 1 NAME\"   ...do it...   python -m eve_profit stop")
    runs = sum(r[1] for r in rows)
    isk = sum(r[2] for r in rows)
    hours = sum(r[3] for r in rows)
    rate = isk / hours
    best = 0.0
    try:
        opps = plan(con, p, 30, False)
        best = opps[0].isk_per_hour if opps else 0.0
    except Exception:                                                   # noqa: BLE001
        pass
    L = [f"AGENT MISSIONS (measured): {rate:,.0f} ISK/hr over {runs} timed run(s), {isk:,.0f} ISK in {hours:.1f} h"
         + (f"  |  best ranked trade/haul: {best:,.0f} ISK/hr" if best else "")]
    for r in sorted(rows, key=lambda r: -(r[2] / r[3]))[:3]:
        L.append(f"   {r[0]}: {r[2] / r[3]:,.0f} ISK/hr ({r[1]} run(s))")
    if best and rate >= 1.2 * best:
        L.insert(0, ">>> DO AGENT MISSIONS FIRST: they beat everything ranked below. Next: python scripts/agent_steps.py next  <<<")
    return "\n".join(L)


def trade_extras(con, g, p, o):
    """For an agent job that needs a trip (offer has to_system): trades worth doing on the way there and back with the spare hold.
    -> (extra ISK, extra minutes, [text lines]) or (0, 0, [])."""
    import dataclasses
    from .journey import DOCK_MIN, plan_journey
    dest = o.get("to_system")
    if not (dest and g is not None and p is not None):
        return 0.0, 0.0, []
    room = max(0.0, p.cargo_m3 - float(o.get("m3", 0.0)))
    here = dataclasses.replace(p, cargo_m3=room)
    there = dataclasses.replace(p, cargo_m3=room, current_system=dest)
    isk = mins = 0.0
    lines = []
    for label, prof, to in (("going", here, dest), ("coming back", there, p.current_system)):
        try:
            r = plan_journey(con, g, prof, to, detour=1)
        except Exception:                                               # noqa: BLE001 (no safe route / unknown system)
            continue
        if r["trade_profit"] <= 0:
            continue
        extra_min = max(0.0, r["hours"] * 60 - r["jumps"] * p.jump_seconds / 60.0 - 2 * DOCK_MIN)
        isk += r["trade_profit"]
        mins += extra_min
        bought = {b[0] for st in r["stops"] for b in st[2]["buy"]}
        for sysname, _, acts in r["stops"]:
            for name, q, cost in acts["buy"][:2]:
                lines.append(f"{label}: buy {q:,} x {name} at {sysname} (-{cost:,.0f})")
            for name, q, rev in acts["sell"][:2]:
                if name in bought:
                    lines.append(f"{label}: sell {q:,} x {name} at {sysname} (+{rev:,.0f})")
        lines.append(f"{label}: trades add {r['trade_profit']:,.0f} ISK for about {extra_min:.0f} more min")
    return isk, mins, lines


def offers_ranked(con, g=None, p=None):
    """Rank the Level 1 agent offers in agent_offers.json by NET ISK per HOUR: (cash after tax + loot at market - items to buy) / (task time + travel both ways)."""
    import json
    from pathlib import Path
    f = Path(__file__).resolve().parents[1] / "agent_offers.json"
    if not f.exists():
        return ""
    d = json.loads(f.read_text(encoding="utf-8"))
    tax, per_jump = d.get("tax", 0.11), d.get("min_per_jump", 3.0)

    def price(item, est):
        try:
            r = con.execute("SELECT MIN(o.price) FROM orders o JOIN types t ON t.type_id=o.type_id WHERE t.name=? AND o.is_buy=0", (item,)).fetchone()
            if r and r[0]:
                return float(r[0]), "mkt"
        except Exception:                                               # noqa: BLE001
            pass
        return float(est), "est"

    rows = []
    for o in d["offers"]:
        if not o.get("available", True):
            continue
        cash = (o.get("isk", 0) + o.get("bonus", 0)) * ((1 - tax) if o.get("taxed", True) else 1.0)
        loot, cost, tags = 0.0, 0.0, []
        for it in o.get("loot", []):
            p, src = price(it["item"], it.get("est", 0))
            loot += p * it["qty"]
            tags.append(f"{it['qty']:,} x {it['item']} ~{p * it['qty']:,.0f}{'' if src == 'mkt' else '?'}")
        for it in o.get("cost", []):
            p, src = price(it["item"], it.get("est", 0))
            cost += p * it["qty"]
            tags.append(f"buy {it['qty']:,} x {it['item']} -{p * it['qty']:,.0f}{'' if src == 'mkt' else '?'}")
        net = cash + loot - cost
        minutes = o.get("task_min", 10) + 2 * o.get("jumps", 0) * per_jump + (2 if o.get("jumps", 0) else 0)
        ex_isk, ex_min, ex_lines = trade_extras(con, g, p, o)
        if ex_isk > 0:
            net, minutes = net + ex_isk, minutes + ex_min
            tags = tags + ["+ TRADES ON THE WAY: " + " | ".join(ex_lines)]
        rows.append((net * 60.0 / minutes, net, minutes, o, tags))
    rows.sort(key=lambda r: -r[0])
    L = ["BEST AGENT OFFERS RIGHT NOW - net ISK per hour incl. travel (cash after tax + loot - buys; times are estimates, ? = estimated price):"]
    for i, (rate, net, minutes, o, tags) in enumerate(rows, 1):
        where = "" if not o.get("jumps") else f"  [AT {o['where']}]"
        extra = ("  (" + "; ".join(tags) + ")") if tags else ""
        L.append(f"  {i}. {rate:>9,.0f} ISK/hr  net {net:>9,.0f} in ~{minutes:.0f} min  {o['agent']} {o['mission']}{where}{extra}")
    return "\n".join(L)


def skill_note(con, g, p, min_hours=8.0):
    """Remind the user when the skill queue is short or empty, and name the first thing to train (plus its book if unowned)."""
    import calendar
    import time as _t
    try:
        rows = [r[0] for r in con.execute("SELECT finish_date FROM skill_queue ORDER BY position") if r[0]]
        if not con.execute("SELECT COUNT(*) FROM character_skills").fetchone()[0]:
            return ""                                                   # never synced: nothing to say
        end = max((calendar.timegm(_t.strptime(x.rstrip("Z")[:19], "%Y-%m-%dT%H:%M:%S")) for x in rows), default=0)
        hours = max(0.0, (end - _t.time()) / 3600.0)
    except Exception:                                                   # noqa: BLE001
        return ""
    if hours >= min_hours:
        return ""
    try:
        from .trainplan import book_list, plan_training
        res = plan_training(con, 24)
        first = res["steps"][0] if res["steps"] else None
        books = book_list(con, g, p, res, hours=1)
    except Exception:                                                   # noqa: BLE001
        first, books = None, []
    L = [f"SKILL QUEUE: only {hours:.1f} h left. Fill it before you leave:  python -m eve_profit trainplan --hours 24"]
    if first:
        L.append(f"   first in your plan: {first['skill']} {first['level']} ({first['minutes'] / 60:.1f} h) - {first['why']}")
    for name, price, where, jumps in books[:1]:
        L.append(f"   BUY THE BOOK FIRST: {name} " + (f"~{price:,.0f} ISK at {where} ({jumps} jumps)" if price else "(no seller found nearby)"))
    return "\n".join(L)


def next_action(con, g, p):
    text = _next_action_core(con, g, p)
    sk = skill_note(con, g, p)
    if sk:
        text = sk + "\n\n" + text
    note = agent_note(con, g, p)
    try:
        ranked = offers_ranked(con, g, p)
    except Exception:                                                   # noqa: BLE001
        ranked = ""
    if ranked:
        note = (note + "\n\n" if note else "") + ranked
    if note:
        text = note + "\n\n" + text
    if getattr(p, "home_location_type", "") == "structure" or (getattr(p, "current_location_id", 0) or 0) > 10 ** 12:
        text += "\n\n" + HOME_NOTE
    return text
