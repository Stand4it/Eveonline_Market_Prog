"""`next`: ONE short instruction at a time. Priority: (1) cash in the liquid stock here, (2) list the single best
high-gap item, (3) the best trade (verify with `check`). Do the step, run `sync`, run `next` again."""
from .along import plan_along
from .planner import plan

AFTER = "Then run:  python -m eve_profit now"


def _better_places(con, g, p, min_extra=50_000.0, rate=None):
    """{type_id: sell_plan row} for stacks here where carrying or a detour to a scanned market pays clearly more than selling now."""
    try:
        from .sellplan import sell_plan
        res = sell_plan(con, g, p, min_value=100_000.0, rate=rate)
    except Exception:                                                   # noqa: BLE001
        return {}
    return {x["tid"]: x for x in res["rows"] if not x["best_label"].startswith(("SELL", "LIST")) and x["extra"] >= min_extra}


def rebuy_note(d):
    """One line when the item is a building material: what rebuying it later would cost against what you get now."""
    if not d.get("used_in") or not d.get("rebuy"):
        return ""
    get_now = max(d.get("list_net", 0.0), d["net"])
    diff = d["rebuy"] - get_now
    verdict = ("selling now and rebuying later is fine (rebuy costs about the same or less)" if diff <= 0.1 * max(get_now, 1)
               else f"rebuying later costs {diff:,.0f} ISK MORE than you get now: hold it if you will build soon")
    return f"   needed later? it is a material in {d['used_in']} blueprint(s): rebuy ~{d['rebuy']:,.0f} vs {get_now:,.0f} now -> {verdict}"


def _next_action_core(con, g, p):
    res = plan_along(con, g, p, p.current_system)
    here = res["sell_here"]
    where = p.current_system
    docked = "" if p.current_location_id else f"(undocked? dock at a {where} station first)\n"
    sells = [d for d in here if d["advice"] != "LIST" and d["net"] >= 50_000]
    if sells:
        total = sum(d["net"] for d in sells)
        L = [f"STEP: SELL NOW in {where} - about {total:,.0f} ISK", docked.rstrip()]
        better = _better_places(con, g, p)
        for d in sells[:8]:
            L.append(f"   {d['sold']:>9,} x {d['name']:<34} @ {d['net'] / max(d['sold'], 1):>12,.2f} each = ~{d['net']:>12,.0f}")
            b = better.get(d["tid"])
            if b:
                L.append(f"      BETTER PLACE: {b['best_label']} pays ~{b['best_net']:,.0f} (+{b['extra']:,.0f} ISK for ~{b['mins']:.0f} min extra)"
                         + (f" [{b['note']}]" if b["note"] else ""))
            if rebuy_note(d):
                L.append(rebuy_note(d))
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
        price = d["listing"] / max(d["qty"], 1)
        slots = res.get("slots")
        L = [f"STEP: LIST 1 item in {where}",
             f"   {d['qty']:,} x {d['name']}",
             f"   price each: {price:,.2f}  (the cheapest sell order in this whole region right now; match or undercut by the smallest step)",
             f"   you receive about {d['list_net']:,.0f} ISK after fees (instant sale would give {d['net']:,.0f})"]
        if rebuy_note(d):
            L.append(rebuy_note(d))
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
    legs = [("going", here, dest)] + ([] if o.get("one_way") else [("coming back", there, p.current_system)])
    for label, prof, to in legs:
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


def offers_rows(con, g=None, p=None):
    """Rank the Level 1 agent offers in agent_offers.json by NET ISK per HOUR: (cash after tax + loot at market - items to buy) / (task time + travel both ways)."""
    import json
    from pathlib import Path
    f = Path(__file__).resolve().parents[1] / "agent_offers.json"
    if not f.exists():
        return []
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
            pr, src = price(it["item"], it.get("est", 0))
            loot += pr * it["qty"]
            tags.append(f"{it['qty']:,} x {it['item']} ~{pr * it['qty']:,.0f}{'' if src == 'mkt' else '?'}")
        for it in o.get("cost", []):
            pr, src = price(it["item"], it.get("est", 0))
            cost += pr * it["qty"]
            tags.append(f"buy {it['qty']:,} x {it['item']} -{pr * it['qty']:,.0f}{'' if src == 'mkt' else '?'}")
        net = cash + loot - cost
        minutes = (o.get("task_min", 10) + (1 if o.get("one_way") else 2) * o.get("jumps", 0) * per_jump
                   + (2 if o.get("jumps", 0) else 0))
        walk = 0
        if o.get("agent_system") and g is not None and p is not None:
            try:
                r_ = g.route(g.id_of(p.current_system), g.id_of(o["agent_system"]), 60, p.avoid_yellow)
                walk = r_.jumps if r_ else 0
            except Exception:                                           # noqa: BLE001
                walk = 0
        if walk:
            minutes += walk * per_jump + 2
            tags = tags + [f"FIRST go to {o['agent_system']} ({walk} jumps, ~{walk * per_jump + 2:.0f} min): missions cannot be accepted remotely"]
        from .bonus import offer_bonus
        b_isk, b_txt = offer_bonus(career_of(o))
        if b_isk:
            net += b_isk
            tags = tags + [f"BONUS PROGRAM: {b_txt}"]
        from .bonus import daily_goal_hits
        hits = daily_goal_hits(o["mission"])
        if hits:
            tags = tags + ["also advances AIR Daily Goals: " + "; ".join(hits)]
        ex_isk, ex_min, ex_lines = trade_extras(con, g, p, o)
        if ex_isk > 0:
            net, minutes = net + ex_isk, minutes + ex_min
            tags = tags + ["+ TRADES ON THE WAY: " + " | ".join(ex_lines)]
        rows.append((net * 60.0 / minutes, net, minutes, o, tags))
    rows.sort(key=lambda r: -r[0])
    return rows


TOP_OFFERS = 5                 # never show more than this many offers
UNMEASURED_BONUS = 1.3         # an unmeasured career ranks as if it paid 30% more: doing it builds the model
BOOK_MAX_WALLET_SHARE = 0.10   # a skill book may cost at most this share of your wallet to be suggested
MIN_BOOK_PRICE = 1000.0        # sell orders below this are junk, not a real skill book price


def career_of(o):
    """Career path of an offer: the 'career' field, else the word(s) in brackets after the agent name ('Industrialist - Producer' -> Industrialist)."""
    if o.get("career"):
        return o["career"]
    ag = o["agent"]
    if ag.startswith("BOTH"):
        return "Industrialist"
    if "(" in ag:
        return ag[ag.index("(") + 1:].rstrip(")").split(" - ")[0].split(",")[0].strip()
    return ag


def measured_careers(con):
    """Careers with at least one timed run whose name mentions them (e.g. 'Agent L1 step 2 Industrialist Venture')."""
    try:
        names = [r[0].lower() for r in con.execute("SELECT activity FROM activity_log WHERE activity LIKE ? AND hours>0", (AGENT_PREFIX + "%",))]
    except Exception:                                                   # noqa: BLE001
        return set()
    keys = {"industrialist": "Industrialist", "explorer": "Explorer", "soldier": "Soldier of Fortune", "enforcer": "Enforcer",
            "mining": "Mining", "entrepreneur": "Industrialist", "courier": "Industrialist"}
    return {c for n in names for k, c in keys.items() if k in n}


def pick_offers(rows, measured, limit=TOP_OFFERS):
    """Best offer of EACH career path first (every career gets tried), then the best of the rest, at most `limit`.
    Unmeasured careers get a bonus so they are tried (that is how the model learns). -> [(row, career, is_measured)]"""
    scored = []
    for r in rows:
        c = career_of(r[3])
        scored.append((r[0] * (1.0 if c in measured else UNMEASURED_BONUS), r, c))
    scored.sort(key=lambda x: -x[0])
    chosen, seen = [], set()
    for sc, r, c in scored:                                             # one per career
        if c not in seen:
            seen.add(c)
            chosen.append((sc, r, c))
    for x in scored:                                                    # then fill with the next best
        if len(chosen) >= limit:
            break
        if x not in chosen and not x[1][3].get("agent", "").startswith("BOTH"):     # a combined offer repeats its parts
            chosen.append(x)
    chosen = sorted(chosen, key=lambda x: -x[0])[:limit]
    return [(r, c, c in measured) for _, r, c in chosen]


def _granted_books(f=None):
    """Lower-case names of skill books that open agent missions grant on acceptance (agent_offers.json 'granted')."""
    import json
    from pathlib import Path
    f = Path(f) if f else Path(__file__).resolve().parents[1] / "agent_offers.json"
    try:
        offers = json.loads(f.read_text(encoding="utf-8")).get("offers", [])
    except (OSError, ValueError):
        return set()
    out = set()
    for o in offers:
        if o.get("available", True):
            for x in o.get("granted", []):
                out.add(x.replace("(skill book)", "").strip().lower())
    return out


def book_sellers(con, g, p, reach_jumps=10):
    """Skill books in your training plan that you have never trained, with every system that sells one (cheapest order there):
    {system name: [(skill, price)]}. Includes books for LATER in the plan: buy them whenever you are there anyway."""
    try:
        from .trainplan import owned_skill_ids, plan_training
        res = plan_training(con, 24)
        owned = owned_skill_ids(con)
        if not owned:
            return {}
    except Exception:                                                   # noqa: BLE001
        return {}
    out, seen = {}, set()
    granted = _granted_books()
    for st in res["steps"]:
        if st["level"] != 1 or st["skill"] in seen or st["skill"].lower() in granted:
            continue                                                    # an open mission GIVES this book when you accept it: never buy it
        row = con.execute("SELECT type_id FROM types WHERE name=? COLLATE NOCASE", (st["skill"],)).fetchone()
        if not row or row[0] in owned:
            continue
        seen.add(st["skill"])
        for sysid, price in con.execute("SELECT system_id,MIN(price) FROM orders WHERE type_id=? AND is_buy=0 AND price>=? GROUP BY system_id",
                                        (row[0], MIN_BOOK_PRICE)):
            if sysid in g.name:
                out.setdefault(g.name[sysid], []).append((st["skill"], float(price)))
    return out


def book_tag(sellers, system, wallet, reserve=100_000.0):
    """'BUY THE SKILL BOOK ...' line for a system, or '' when none is sold there or you cannot afford it."""
    L = []
    for skill, price in sorted(sellers.get(system, []), key=lambda x: x[1]):
        if price <= BOOK_MAX_WALLET_SHARE * wallet and price <= wallet - reserve:      # never put a big share of your ISK into one book
            L.append(f"WHILE AT {system}: buy the {skill} skill book (~{price:,.0f} ISK) and INJECT it (Inventory > right-click > Inject Skill), then queue it")
    return L


def books_here_note(con, g, p):
    try:
        lines = book_tag(book_sellers(con, g, p), p.current_system, p.wallet_isk)
    except Exception:                                                   # noqa: BLE001
        return ""
    return "\n".join("BUY NOW - " + l for l in lines)


def offers_ranked(con, g=None, p=None, limit=TOP_OFFERS):
    rows = offers_rows(con, g, p)
    if not rows:
        return ""
    measured = measured_careers(con)
    picked = pick_offers(rows, measured, limit)
    try:
        sellers = book_sellers(con, g, p) if g is not None and p is not None else {}
    except Exception:                                                   # noqa: BLE001
        sellers = {}
    L = [f"TOP {len(picked)} AGENT OFFERS - one per career path first, unmeasured careers favoured (they teach the model). "
         f"Net ISK/hr incl. travel; ? = estimated price"]
    for i, ((rate, net, minutes, o, tags), career, known) in enumerate(picked, 1):
        L.append(f"  #{i}  {rate:>9,.0f} ISK/hr   net {net:,.0f} ISK in ~{minutes:.0f} min   [{career}: "
                 + ("measured" if known else "NOT MEASURED YET - doing it builds the model") + "]")
        L.append(f"      {o['agent']}")
        L.append(f"      {o['mission']}")
        if o.get("jumps"):
            L.append(f"      at: {o['where']}")
        for t in tags:
            if t.startswith("+ TRADES ON THE WAY: "):
                L.append("      + trades on the way:")
                L += ["          " + x.strip() for x in t[len("+ TRADES ON THE WAY: "):].split(" | ")]
            else:
                L.append(f"      - {t}")
        if g is not None and p is not None:
            for sysname in dict.fromkeys(x for x in (p.current_system, o.get("agent_system"), o.get("to_system")) if x):
                for line in book_tag(sellers, sysname, p.wallet_isk):
                    L.append(f"      * {line}")
        L.append("")
    hidden = len(rows) - len(picked)
    if hidden > 0:
        L.append(f"  ({hidden} lower-ranked offers hidden; all of them: python -m eve_profit agents)")
    return "\n".join(L).rstrip()


def _section(title, body):
    return f"{'=' * 70}\n {title}\n{'=' * 70}\n{body}" if body else ""


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
        from .trainplan import book_list, plan_training, trainable_now
        res = plan_training(con, 24)
        now_steps = trainable_now(con, res)
        books = book_list(con, g, p, res, hours=1)
    except Exception:                                                   # noqa: BLE001
        now_steps, books = [], []
    L = [f"SKILL QUEUE: only {hours:.1f} h left. Fill it before you leave."]
    if now_steps:
        st = now_steps[0]
        L.append(f"   QUEUE NOW (no purchase needed): {st['skill']} {st['level']} ({st['minutes'] / 60:.1f} h) - {st['why']}")
        L.append("   (in game: Skills > find it > + / Train Now; the full ordered list: python -m eve_profit trainplan --hours 24)")
    else:
        L.append("   Nothing in your plan can be queued without a new skill book (see below).")
    for name, price, where, jumps in books[:1]:
        rate = _agent_rate(con)
        trip_min = 2 * jumps * p.jump_seconds / 60.0 + 4
        L.append(f"   BOOK TRIP, decide: {name} " + (f"~{price:,.0f} ISK at {where} ({jumps} jumps)" if price else "(no seller found nearby)"))
        if price:
            lost = rate * trip_min / 60.0
            L.append(f"      a special trip is ~{trip_min:.0f} min = ~{lost:,.0f} ISK of agent income lost, plus the book.")
            if name == "Accounting":
                per = 0.075 * 0.11
                L.append(f"      Accounting I only cuts sales tax by {per * 100:.2f}% of what you SELL: it repays {price + lost:,.0f} ISK after "
                         f"~{(price + lost) / per / 1e6:,.0f}M ISK of sales. Not worth a trip while you earn from agents.")
            L.append(f"      => buy it only when a mission or trade already takes you to {where}, or once you trade/sell real volume.")
    return "\n".join(L)


def _agent_rate(con):
    try:
        r = con.execute("SELECT SUM(isk), SUM(hours) FROM activity_log WHERE activity LIKE ?", (AGENT_PREFIX + "%",)).fetchone()
        return (r[0] / r[1]) if r and r[1] else 0.0
    except Exception:                                                   # noqa: BLE001
        return 0.0


def next_action_all(con, g, p):
    core = _next_action_core(con, g, p)
    parts = []
    sk = "\n\n".join(x for x in (books_here_note(con, g, p), skill_note(con, g, p)) if x)
    if sk:
        parts.append(_section("SKILLS", sk))
    note = agent_note(con, g, p)
    if note:
        parts.append(_section("AGENT MISSIONS - measured", note))
    try:
        ranked = offers_ranked(con, g, p)
    except Exception:                                                   # noqa: BLE001
        ranked = ""
    if ranked:
        parts.append(_section("AGENT OFFERS", ranked))
    parts.append(_section("TRADING / HAULING", core))
    text = "\n\n".join(x for x in parts if x)
    if getattr(p, "home_location_type", "") == "structure" or (getattr(p, "current_location_id", 0) or 0) > 10 ** 12:
        text += "\n\n" + HOME_NOTE
    return text


DONE = "When done:  python -m eve_profit stop   (agent missions: wait 2 minutes first)   then   python -m eve_profit sync   then   python -m eve_profit next      (or  python -m eve_profit now  = sync + fresh prices + next)"


def _unit_price(con, item, est):
    """Cheapest sell order for an item by name (what you pay now), else the estimate from agent_offers.json."""
    try:
        r = con.execute("SELECT MIN(o.price) FROM orders o JOIN types t ON t.type_id=o.type_id WHERE t.name=? AND o.is_buy=0", (item,)).fetchone()
        if r and r[0]:
            return float(r[0])
    except Exception:                                                   # noqa: BLE001
        pass
    return float(est or 0)


def _agent_step(con, g, p):
    """The ONE best agent offer as an ordered chain of sub-steps (go, accept, time, buy, deliver, stop); (None, 0) if no offer."""
    rows = offers_rows(con, g, p)
    if not rows:
        return None, 0.0
    (rate, net, minutes, o, tags), career, known = pick_offers(rows, measured_careers(con), 1)[0]
    agents = o.get("agents") or [o["agent"]]
    n = 0
    L = [f"AGENT MISSION: {o['agent']}",
         f"   {o['mission']}",
         f"   about {net:,.0f} ISK net in ~{minutes:.0f} min = {rate:,.0f} ISK/hr   [{career}" + ("" if known else ", not measured yet: builds the model") + "]"]

    def add(text):
        nonlocal n
        n += 1
        L.append(f"   {n}. {text}")
    for t in tags:
        if t.startswith("FIRST go to "):
            add(t.replace("FIRST go to ", "Fly to ", 1))
    if o.get("needs"):
        L.append(f"   NEEDS: {o['needs']}")
    acc = o.get("accept") or [{"agent": a_} for a_ in agents]
    for x in acc:                                                       # each mission on its own line
        add(f"ACCEPT {x['agent']}'s mission in person" + (f": {x['task']}" if x.get("task") else "")
            + (f"   [you get: {x['grants']}]" if x.get("grants") else ""))
    add(f'Start the timer:  python -m eve_profit start --activity "{o.get("timer_name") or "Agent L1 " + o["agent"].split(" (")[0] + " " + o["mission"][:40]}"')
    for it in o.get("cost", []):
        add(f"BUY  {it['qty']:>6,} x {it['item']}  (about {_unit_price(con, it['item'], it.get('est', 0)):,.0f} each):  python -m eve_profit buy --item \"{it['item']}\" --qty {it['qty']}")
    for t in tags:
        if t.startswith("+ TRADES ON THE WAY: "):
            for x in t[len("+ TRADES ON THE WAY: "):].split(" | "):
                add("On the way: " + x.strip())
    add(f"Hand in / deliver at {o.get('where') or 'the agent'}" + (f" ({o['to_system']})" if o.get("to_system") else "") + " and complete the mission.")
    return "\n".join(L), rate


def _timer(name):
    """Every step ends with the command that times it, so each run is classified for the ISK/hr model."""
    return f'   Time it:  python -m eve_profit start --activity "{name}"'


def _name_of(step):
    """Activity name for a step from its first line (kept stable so repeated runs add up)."""
    first = step.splitlines()[0]
    lo = first.lower()
    rest = first.split(":", 1)[-1].strip() if ":" in first else first
    if lo.startswith("step: sell now"):
        return "Market sell stock " + rest.replace("SELL NOW in ", "").split(" - ")[0]
    if lo.startswith("step: list"):
        item = step.splitlines()[1].strip().split(" x ", 1)[-1] if len(step.splitlines()) > 1 else ""
        return f"Market list {item}".strip()
    if lo.startswith("step: buy a skill book"):
        return "Skills buy book"
    if lo.startswith("step: queue a skill"):
        return "Skills queue"
    if lo.startswith("step: test"):
        return "Test " + first.split("TEST ", 1)[-1].split(" (")[0]
    if lo.startswith("step: haul"):
        return "Hauling stock to " + first.split(" to ", 1)[-1].split(" (")[0]
    if lo.startswith("step: upgrade gear"):
        return "Gear upgrade"
    if lo.startswith("step: "):
        lines = step.splitlines()
        return (first[6:].split("(")[0].strip().title() + " " + (lines[1].strip()[:40] if len(lines) > 1 else "")).strip()
    return rest


def _chain(steps):
    """One step = print it as is; several = a numbered chain to do in this order."""
    steps = [x for x in steps if x]
    if len(steps) == 1:
        return steps[0]
    L = [f"TODAY'S CHAIN - {len(steps)} parts, do them in this order, then sync and next:", ""]
    for i, t in enumerate(steps, 1):
        L.append(f"[{i}/{len(steps)}] {t}")
        L.append("")
    return "\n".join(L).rstrip()


def _upgrade_step(con, g, p):
    try:
        from .along import plan_along
        ups = plan_along(con, g, p, p.current_system).get("upgrades", [])
    except Exception:                                                   # noqa: BLE001
        return ""
    if not ups:
        return ""
    L = ["STEP: UPGRADE GEAR (you can now afford a better one; the old one is not needed)"]
    for u in ups[:2]:
        L.append(f"   sell {u['qty']} x {u['item']} (about {u['sell_net']:,.0f} ISK listed), buy {u['qty']} x {u['upgrade']} (about {u['new_cost']:,.0f} ISK): "
                 f"costs you only {u['out_of_pocket']:,.0f} ISK")
        L.append(f'   python -m eve_profit buy --item "{u["upgrade"]}" --qty {u["qty"]}')
    L.append("   Keep the new one stowed in a station hangar until needed. You can buy it remotely by placing a BUY order at that station (check range in game).")
    return "\n".join(L)


def next_action(con, g, p, full=False):
    """KISS: ONE task or ONE chain of tasks that belong together, in order: sell stock here / list one item here, buy a skill book sold
    here, queue a skill, then the best agent mission (if it beats the best trade) else the best trade. `next --all` = everything."""
    if full:
        return next_action_all(con, g, p)
    core = _next_action_core(con, g, p)
    upg = _upgrade_step(con, g, p)
    home = ("\n\n" + HOME_NOTE) if (getattr(p, "home_location_type", "") == "structure" or (getattr(p, "current_location_id", 0) or 0) > 10 ** 12) else ""
    steps, selling = [], core.startswith(("STEP: SELL NOW", "STEP: LIST"))
    if selling:
        steps.append(core.rsplit("\n" + AFTER, 1)[0] if AFTER in core else core)
    if upg:
        steps.append(upg)
    book = books_here_note(con, g, p)
    if book:
        steps.append("STEP: BUY A SKILL BOOK HERE\n   " + book.splitlines()[0].replace("BUY NOW - ", ""))
    sk = skill_note(con, g, p)
    queue = [l.strip() for l in sk.splitlines() if "QUEUE NOW" in l]
    if queue:
        steps.append("STEP: QUEUE A SKILL (takes 30 seconds, free)\n   " + queue[0].replace("QUEUE NOW (no purchase needed): ", ""))
    agent, rate = _agent_step(con, g, p)
    # ---- the MAIN activity: every candidate scored in ISK per hour, same currency, best one wins -----------------------------------
    cands = []                                                   # (ISK/hr, label, step text, note)
    try:
        from .progress import experiment_candidates, progress_isk, run_counts, values
        counts, vals = run_counts(con), values()
    except Exception:                                            # noqa: BLE001
        counts, vals = {}, None
    try:                                                          # AIR Daily Goals pay real ISK (445,000 seen): a main candidate until claimed today
        from .bonus import daily_goal_due, daily_goal_program, daily_goal_step
        dg = daily_goal_program()
        if dg and dg.get("reward_isk") and daily_goal_due(con):
            cands.append((dg["reward_isk"] * 60.0 / dg.get("minutes_estimate", 20), "AIR daily goals", daily_goal_step(dg), "once a day"))
    except Exception:                                            # noqa: BLE001
        pass
    if agent:
        rate_adj = rate
        try:
            rows_ = offers_rows(con, g, p)
            (r_, net_, min_, o_, tags_), career_, known_ = pick_offers(rows_, measured_careers(con), 1)[0]
            rate_adj = (net_ + progress_isk(career_, counts, vals)) * 60.0 / max(min_, 1.0)
        except Exception:                                        # noqa: BLE001
            pass
        cands.append((rate_adj, "agent mission", agent,
                      f"{rate:,.0f} cash + progression/model value"))
    try:
        for r_, label_, text_ in experiment_candidates(con, counts, vals):
            cands.append((r_, label_, text_, "never timed: builds the model"))
    except Exception:                                            # noqa: BLE001
        pass
    try:
        from .haul import haul_option, haul_step
        h = haul_option(con, g, p)
    except Exception:                                            # noqa: BLE001
        h = None
    if h:
        cands.append((h["rate_hr"], f"haul stock to {h['dest']}", haul_step(h), "sell-now prices at the far market"))
    best_trade, trade_text = 0.0, None
    if not selling:
        try:
            opps = plan(con, p, 30, False)
            best_trade = opps[0].isk_per_hour if opps else 0.0
        except Exception:                                        # noqa: BLE001
            best_trade = 0.0
        if best_trade > 0 or not cands:
            cands.append((best_trade, "best trade / planned activity", core, "from the last scan"))
            trade_text = core
    cands.sort(key=lambda c: -c[0])
    why = ""
    exp_note = ""
    try:                                                         # MODEL-BUILDING turn: an unmodeled, unlocked activity goes first now and then
        import json as _j
        from .catalog import experiment_step, pick_experiment
        meta = {r[0]: r[1] for r in con.execute("SELECT key,value FROM meta WHERE key IN ('start_count','last_exp','seen_unlocked')")}
        counter = int(meta.get("start_count", 0))                # counts timers you START, not times you look at `next`
        last_exp = int(meta.get("last_exp", 0))
        seen = set(_j.loads(meta.get("seen_unlocked", "[]")))
        best_known = max((c[0] for c in cands), default=0.0)
        act, reason, new_seen = pick_experiment(con, p.wallet_isk, best_known, counter, last_exp, seen)
        if "seen_unlocked" not in meta:                          # first ever call: just remember what is already unlocked
            con.execute("INSERT OR REPLACE INTO meta VALUES('seen_unlocked',?)", (_j.dumps(sorted(new_seen)),))
        if act:
            step_txt = experiment_step(act, reason)
            if act["id"] == "station_trading":                    # never point at `next` itself: show the actual best trade
                try:
                    opps_ = plan(con, p, 5, False)
                    if opps_:
                        o_ = opps_[0]
                        step_txt = (f"STEP: TEST Station / hub trading ({reason})\n   Best trade right now: {o_.description}\n"
                                    f"   about {o_.net_isk:,.0f} ISK in {o_.hours * 60:.0f} min ({o_.isk_per_hour:,.0f} ISK/hr). Confirm live prices first:  "
                                    "python -m eve_profit check --pick 1   then   python -m eve_profit go --pick 1 --send\n"
                                    "   Unmodeled: 3 timed runs turn the guess into your own number.")
                    else:
                        step_txt = None                           # no ranked trade right now: do not offer an empty test
                except Exception:                                # noqa: BLE001
                    step_txt = None
            if step_txt is None:
                act = None
        if act:
            if act["id"] == "mining_belt":
                try:
                    from .mining_sites import recommend
                    where = recommend(con)
                    if where:
                        step_txt = step_txt.replace("\n   about", "\n" + where + "\n   about", 1)
                except Exception:                                # noqa: BLE001
                    pass
            cands.insert(0, (float("inf"), f"TEST {act['name']}", step_txt, reason))
            exp_note = f"MODEL-BUILDING TURN: {reason}. The best-ISK/hr options stay in the list below."
        con.commit()
    except Exception:                                            # noqa: BLE001
        pass
    if cands:
        steps.append(cands[0][2])
        trade_text = cands[0][2] if cands[0][1].startswith("best trade") else None
        if len(cands) > 1:
            why = "WHY THIS ONE (ISK per hour, same yardstick for all): " + "; ".join(
                f"{'>> ' if i == 0 else ''}{c[1]} " + ("(model turn)" if c[0] == float("inf") else f"{c[0]:,.0f}") for i, c in enumerate(cands[:5]))
            why += "   (cash + the value of progress and of teaching the model; numbers editable in progress_values.json)"
    if trade_text:
        steps.append(trade_text.rsplit("\n" + AFTER, 1)[0])
    if selling or trade_text:
        from .bonus import market_lines
        bl = market_lines()
        if bl:
            steps[0 if selling else -1] += "\n" + "\n".join(bl)
    steps = [x if x.startswith("AGENT MISSION") else x + "\n" + _timer(_name_of(x)) for x in steps]
    out = _chain(steps) + (("\n\n" + exp_note) if exp_note else "") + (("\n\n" + why) if why else "") + "\n\n" + DONE
    if not selling or len(steps) > 1:
        out += "\n(more detail: python -m eve_profit next --all)"
    return out + home
