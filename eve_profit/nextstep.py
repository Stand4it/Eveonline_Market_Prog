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


def _detour_step(con, g, p, where, sells, d, b):
    """SELL <ITEM> n JUMPS AWAY in <place>: the stack pays clearly more there, even with several trips of your hold."""
    place = b["best_label"].split("DETOUR to ", 1)[-1].strip()
    jumps = 1
    try:
        jumps = g.reach(g.id_of(where), 10, p.avoid_yellow)[g.id_of(place)].jumps
    except Exception:                                                   # noqa: BLE001
        pass
    trips = int(b.get("trips") or 1)
    per_trip = -(-d["sold"] // max(trips, 1))
    bid = station = None
    try:
        r = con.execute("SELECT o.price, s.name FROM orders o LEFT JOIN stations s ON s.station_id=o.location_id WHERE o.type_id=? AND o.is_buy=1 AND o.system_id=? "
                        "ORDER BY o.price DESC LIMIT 1", (d["tid"], g.id_of(place))).fetchone()
        if r:
            bid, station = r[0], r[1]
    except Exception:                                                   # noqa: BLE001
        pass
    item = d["name"]
    L = [f"STEP: SELL {item.upper()} {jumps} JUMP{'S' if jumps != 1 else ''} AWAY in {place} - about {b['best_net']:,.0f} ISK",
         f"   {d['sold']:>9,} x {item:<34} @ {b['best_net'] / max(d['sold'], 1):>12,.2f} each = ~{b['best_net']:>12,.0f}   (net of tax)",
         f"   that is +{b['extra']:,.0f} ISK more than selling in {where} (~{d['net']:,.0f}), for about {b['mins']:.0f} more minutes",
         "   HOW:"]
    n = 0

    def add(t):
        nonlocal n
        n += 1
        L.append(f"   {n}. {t}")
    add(f"Load {per_trip:,} x {item} into your ship's hold" + (f" (trip 1 of {trips})" if trips > 1 else ""))
    add(f"Fly {jumps} jump{'s' if jumps != 1 else ''} to {place}" + (f" and dock at {station}" if station else " and dock"))
    add(f"Market > {item} > Sell > pick the HIGHEST buy order" + (f" (about {bid:,.2f} ISK each)" if bid else "") + ": instant sale, no listing")
    if trips > 1:
        add(f"Fly back and repeat for the other {d['sold'] - per_trip:,} ({trips - 1} more trip{'s' if trips > 2 else ''})")
    else:
        add(f"Fly back to {where}")
    L.append(f"   QUICK ALTERNATIVE: sell it all right here for ~{d['net']:,.0f} ISK in about 3 minutes (the plan above pays more per minute only if you have nothing better to do).")
    try:
        from .reprocess import describe as _rdesc, refine_option
        ro = refine_option(con, g, p, d["name"], d["sold"], d["net"])
        if ro:
            L += _rdesc(d["name"], ro)
    except Exception:                                                   # noqa: BLE001
        pass
    others = [x for x in sells[1:6]]
    if others:
        L.append(f"   also sell here in {where}: " + "; ".join(f"{x['sold']:,} x {x['name']} (~{x['net']:,.0f})" for x in others))
    L.append(AFTER)
    return "\n".join(L)


KEEP_NOTES = []                                                  # why stacks here were NOT offered for sale (shown in `next --plan`)


def _next_action_core(con, g, p):
    res = plan_along(con, g, p, p.current_system)
    here = res["sell_here"]
    where = p.current_system
    docked = "" if p.current_location_id else f"(undocked? dock at a {where} station first)\n"
    sells = [d for d in here if d["advice"] != "LIST" and d["net"] >= 50_000]
    better, keep_lines = {}, []
    KEEP_NOTES.clear()
    try:                                                         # items you chose to hold for a better market are never offered for sale
        from .invoverlay import hold_names
        _hold = hold_names(con)
        for d in [x for x in sells if any(h and h in x["name"].lower() for h in _hold)]:        # the part of the name you typed is enough
            keep_lines.append(f"   keep {d['sold']:,} x {d['name']}: on your HOLD list (better price elsewhere; release: done --goal \"release {d['name']}\")")
            sells.remove(d)
    except Exception:                                            # noqa: BLE001
        pass
    if sells:
        better = _better_places(con, g, p)
        try:                                                     # light stacks that pay several times more far away: keep them, do not dump them here
            from .worldprices import hold_advice, keep_line
            vol_ = {r[0]: (r[1] or 0.0) for r in con.execute("SELECT type_id,volume FROM types")}
            for d in list(sells):
                b_ = better.get(d["tid"])
                adv = hold_advice(con, d["tid"], d["sold"], vol_.get(d["tid"], 0.0), max(d["net"], b_["best_net"] if b_ else 0.0))
                if adv:
                    keep_lines.append("   " + keep_line(d["name"], d["sold"], adv))
                    sells.remove(d)
        except Exception:                                        # noqa: BLE001
            pass
    try:                                                         # stacks in this station that are skipped for other reasons: say why (plan view)
        for l in res.get("losses", []):
            keep_lines.append(f"   keep {l['qty']:,} x {l['name']}: the best price here ({l['best_here']:,.0f}) is BELOW what you paid ({l['cost']:,.0f})"
                              + (f"; {l['alt_name']} pays {l['alt'][0]:,.0f} ({l['alt_jumps']} jumps)" if l.get("alt") else ""))
        for n, q in res.get("no_bids", []):
            keep_lines.append(f"   keep {q:,} x {n}: no buy order for it " + ("at the station you are docked in (" + str(res.get("dock")) + "); the buyers are elsewhere" if res.get("dock") else "on your route here"))
        for n in res.get("on_market", []):
            keep_lines.append(f"   keep {n}: you already have a sell order for it on the market")
        for n in res.get("kept_gear", []):
            keep_lines.append(f"   keep {n}: on your keep list (gear you will use)")
    except Exception:                                            # noqa: BLE001
        pass
    KEEP_NOTES.extend(keep_lines)
    if sells:
        total = sum(d["net"] for d in sells)
        try:                                                     # so `stop` can take exactly these stacks out of the stock (ESI assets lag an hour)
            from .invoverlay import remember_sell_step
            remember_sell_step(con, g.id_of(where), [(d["tid"], d["sold"]) for d in sells])
        except Exception:                                        # noqa: BLE001
            pass
        L = [f"STEP: SELL NOW in {where} - about {total:,.0f} ISK", docked.rstrip()]
        detour = None                                            # the biggest stack has a clearly better market a few jumps away: THAT becomes the step
        for d in sells[:8]:
            b = better.get(d["tid"])
            if b and detour is None and d is sells[0] and b["best_label"].startswith("DETOUR to"):
                detour = (d, b)
                break
        if detour:
            return _detour_step(con, g, p, where, sells, detour[0], detour[1])
        for d in sells[:8]:
            L.append(f"   {d['sold']:>9,} x {d['name']:<34} @ {d['net'] / max(d['sold'], 1):>12,.2f} each = ~{d['net']:>12,.0f}")
            b = better.get(d["tid"])
            if b:
                L.append(f"      BETTER PLACE: {b['best_label']} pays ~{b['best_net']:,.0f} (+{b['extra']:,.0f} ISK for ~{b['mins']:.0f} min extra)"
                         + (f" [{b['note']}]" if b["note"] else ""))
            if rebuy_note(d):
                L.append(rebuy_note(d))
            try:                                                 # an ore or item we have refining data for: refine vs sell raw
                from .reprocess import describe as _rdesc, refine_option
                ro = refine_option(con, g, p, d["name"], d["sold"], d["net"])
                if ro:
                    L += _rdesc(d["name"], ro)
            except Exception:                                    # noqa: BLE001
                pass
        if len(sells) > 8:
            L.append(f"   ...and {len(sells) - 8} more smaller stacks (all marked SELL NOW in `along`)")
        L += keep_lines
        try:                                                     # the game's destination = the station with the best buy order (also clears an old waypoint)
            from .tradestep import STATION
            row = con.execute("SELECT location_id FROM orders WHERE is_buy=1 AND system_id=? AND type_id=? AND volume_remain>0 AND location_id IS NOT NULL "
                              "ORDER BY price DESC LIMIT 1", (g.id_of(where), sells[0]["tid"])).fetchone()
            if row:
                STATION[L[0]] = int(row[0])
        except Exception:                                        # noqa: BLE001
            pass
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
        if o.kind == "trade":
            from .tradestep import fresh, trade_step
            o = next((x for x in (fresh(con, g, p, y) for y in opps[:3] if y.kind == "trade") if x), o)
            ts = trade_step(con, g, p, o)
            if ts:
                return ts + "\n" + AFTER
        if o.kind == "liquidate" and getattr(o, "waypoints", None):          # stock to sell elsewhere: ONE action = the next jump; the sale comes up when you are there
            hop = g.name[o.waypoints[0]]
            load = ""
            try:
                if (o.detail or {}).get("from_sys") == g.id_of(p.current_system):          # the stock lies in this hangar: load it first (same action, then jump)
                    import re as _re
                    mm = _re.match(r"Collect \+ sell ([\d,]+ x .+?) \(stock at", o.description)
                    if mm:
                        load = f"load {mm.group(1)} into your ship, then "
            except Exception:                                    # noqa: BLE001
                pass
            return (f"STEP: FLY to {hop}\n   DO ONLY THIS: {load}fly to {hop} and stop there. Then run  python -m eve_profit next  (it plans again from there).\n"
                    f"   LATER: {o.description}: about {o.net_isk:,.0f} ISK in {o.hours * 60:.0f} min ({o.isk_per_hour:,.0f} ISK/hr; confirm the buy-order price in the game before you sell)\n" + AFTER)
        L = [f"STEP: {o.kind.upper()} (nothing left to sell here; best of everything ranked by ISK/hr)",
             f"   {o.description}",
             f"   profit about {o.net_isk:,.0f} ISK in {o.hours * 60:.0f} min ({o.isk_per_hour:,.0f} ISK/hr)"]
        if o.kind == "trade":
            L.append("   FIRST confirm live prices:   python -m eve_profit check --pick 1")
        elif o.kind == "liquidate":
            L.append("   (`check` does not work on stock you own: confirm the buy-order price in the game before you sell.)")
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
            how = ""
            if g is not None and p is not None:
                try:
                    from .acquire import best_way
                    w_ = best_way(con, g, p, it["item"], it["qty"], o.get("agent_system") or o.get("to_system"))
                    if w_ and w_["mode"] != "held":
                        pr, src, how = w_["cost"] / max(it["qty"], 1), "mkt", f" ({w_['mode']})"
                    elif w_:
                        pr, src, how = 0.0, "mkt", " (held)"
                except Exception:                                       # noqa: BLE001
                    pass
            cost += pr * it["qty"]
            tags.append(f"buy {it['qty']:,} x {it['item']} -{pr * it['qty']:,.0f}{how}{'' if src == 'mkt' else '?'}")
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
    try:
        from .listings import import_snapshots
        import_snapshots(con)                                    # new screenshots I recorded: compare with the stored lists (new / gone / change rate)
    except Exception:                                            # noqa: BLE001
        pass
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


LAST_OFFER = {}
AGENT_FIRST = {"text": ""}


def _hop_step(g, p, con_=None):
    def hop_to(system, why, lines):
        from .haul import _hop
        nm, left, total = _hop(g, p, system)
        if not nm:
            return ""
        try:                                                            # stock lying here: pick it up first (consolidates your inventory as you travel)
            from .tripplus import pickup_step
            ps = pickup_step(con_, g, p, system)
            if ps:
                return ps
        except Exception:                                               # noqa: BLE001
            pass
        return (f"STEP: FLY to {nm}\n   DO ONLY THIS: fly to {nm} and stop there. Then run  python -m eve_profit next  (it plans again from there).\n"
                f"   LATER: {why} ({left} jumps to {system})" + ((": " + " | ".join(lines)) if lines else ""))
    return hop_to


def _agent_first(con, g, p, o, ways):
    """An agent mission as ONE action: get what it needs where that is cheapest, then fly to the agent (one jump per step), then accept / do / hand in."""
    hop_to = _hop_step(g, p, con)
    try:
        from .acquire import first_action
        for w_ in ways:
            if w_ and w_["mode"] != "held":
                t = first_action(con, g, p, w_, hop_to)
                if t:
                    return t
        agent_sys = o.get("agent_system") or o.get("to_system")
        if agent_sys and agent_sys != p.current_system:
            return hop_to(agent_sys, f"{o['agent'].split(' (')[0]}'s mission: accept it in person, then do it (missions cannot be accepted remotely)", [o.get("mission", "")[:120]])
        from .agentchain import stage_text
        return stage_text(con, g, p, o)
    except Exception:                                                   # noqa: BLE001
        return ""


def _agent_step(con, g, p):
    """The ONE best agent offer as an ordered chain of sub-steps (go, accept, time, buy, deliver, stop); (None, 0) if no offer."""
    rows = offers_rows(con, g, p)
    if not rows:
        return None, 0.0
    (rate, net, minutes, o, tags), career, known = pick_offers(rows, measured_careers(con), 1)[0]
    LAST_OFFER["o"] = o
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
    ways = []
    for it in o.get("cost", []):
        w_ = None
        try:
            from .acquire import best_way
            w_ = best_way(con, g, p, it["item"], it["qty"], o.get("agent_system") or o.get("to_system"), live=True)       # today's prices before any trip
        except Exception:                                               # noqa: BLE001
            w_ = None
        ways.append(w_)
        if w_ and w_["mode"] == "held":
            add(f"{it['qty']:>6,} x {it['item']}: you already hold it")
        elif w_:
            add(f"GET   {it['qty']:>6,} x {it['item']}: " + " | ".join(w_["lines"]))
        else:
            add(f"BUY  {it['qty']:>6,} x {it['item']}  (about {_unit_price(con, it['item'], it.get('est', 0)):,.0f} each):  python -m eve_profit buy --item \"{it['item']}\" --qty {it['qty']}")
    for t in tags:
        if t.startswith("+ TRADES ON THE WAY: "):
            for x in t[len("+ TRADES ON THE WAY: "):].split(" | "):
                add("On the way: " + x.strip())
    add(f"Hand in / deliver at {o.get('where') or 'the agent'}" + (f" ({o['to_system']})" if o.get("to_system") else "") + " and complete the mission.")
    try:                                                                # hauling / agents / cheap needs on the way to the agent (plan view)
        from .tripplus import extras as _extras
        ex = _extras(con, g, p, o.get("agent_system") or o.get("to_system"))
        if ex["lines"]:
            L.append("   ALSO ON THE WAY (to earn more on this trip):")
            L += ["      " + x for x in ex["lines"][:8]]
    except Exception:                                                   # noqa: BLE001
        pass
    AGENT_FIRST["text"] = _agent_first(con, g, p, o, ways)
    return "\n".join(L), rate


def _timer(name, con=None):
    """Every step ends with the command that times it, so each run is classified for the ISK/hr model. A timer already running for this task
    (a later step of the same chain) is only mentioned, not started twice."""
    try:
        import json as _j
        r = con.execute("SELECT value FROM meta WHERE key='session'").fetchone() if con is not None else None
        if r and _j.loads(r[0]).get("activity") == name:
            return f'   Timer: already running for "{name}". Stop it only when the whole task is finished.'
    except Exception:                                                   # noqa: BLE001
        pass
    return f'   Time it:  python -m eve_profit start --activity "{name}"'


def finish_block(step):
    """The ONE step followed by its commands in the order you type them: start the timer, do it, done (if the step has one), stop, sync, next.
    The step's own 'When it is done run ...' lines and its Time it / Timer line are folded into that list so nothing appears twice."""
    import re
    lines, timer, needs_done = [], None, False
    for ln in step.split("\n"):
        if re.match(r"^\s*(Time it:|Timer:)", ln):
            timer = ln.strip()
            continue
        if re.match(r"^\s*When (it is |)(done|sent|accepted)[^:]*run:", ln, re.I) or ("python -m eve_profit done" in ln and ln.strip().lower().startswith("when")):
            needs_done = True
            continue
        if "python -m eve_profit done" in ln:
            needs_done = True
        lines.append(ln)
    while lines and not lines[-1].strip():
        lines.pop()
    body = ["§      " + l.strip() if l.strip() else "" for l in lines]            # '§' = highlighted by style.task_block (the step sits at its number)
    out = ["   COMMANDS FOR THIS STEP, IN ORDER:"]
    n = 1
    if timer and timer.startswith("Time it:"):
        out.append(f"   {n}. Start the timer:  " + timer.split("Time it:", 1)[1].strip())
        n += 1
    elif timer:
        out.append(f"   {n}. {timer}")
        n += 1
    out.append(f"   {n}. DO THIS:")
    out += body
    n += 1
    is_sell = step.lstrip().upper().startswith("STEP: SELL NOW")
    stop_txt = ("Stop the timer (also marks the step done):  python -m eve_profit stop" if needs_done else
                "Stop the timer (also takes the sold items out of your stock):  python -m eve_profit stop" if is_sell else "Stop the timer:  python -m eve_profit stop")
    out += [f"   {n}. {stop_txt}   (agent missions: wait 2 minutes first)",
            f"   {n + 1}. Update from the game:  python -m eve_profit sync      (stop + sync in one go:  python -m eve_profit stopsync)",
            f"   {n + 2}. Next step:  python -m eve_profit next      (or  python -m eve_profit now  = sync + fresh prices + next)"]
    return "\n".join(out)


def _name_of(step):
    """Activity name for a step from its first line (kept stable so repeated runs add up)."""
    first = step.splitlines()[0]
    lo = first.lower()
    rest = first.split(":", 1)[-1].strip() if ":" in first else first
    if lo.startswith("step: sell now"):
        return "Market sell stock " + rest.replace("SELL NOW in ", "").split(" - ")[0]
    if lo.startswith("step: sell ") and " away in " in lo:             # SELL SCORDITE 1 JUMP AWAY in Axiosere - ...
        return "Market sell stock " + first.split(" AWAY in ", 1)[-1].split(" - ")[0].strip()
    if lo.startswith("step: list"):
        item = step.splitlines()[1].strip().split(" x ", 1)[-1] if len(step.splitlines()) > 1 else ""
        return f"Market list {item}".strip()
    if lo.startswith("step: buy a skill book"):
        return "Skills buy book"
    if lo.startswith("step: queue a skill"):
        return "Skills queue"
    if lo.startswith("step: air daily goals"):
        return "AIR Daily Goals"
    if lo.startswith("step: update the model"):
        return "Update the model from the game"
    if lo.startswith("step: test"):
        return "Test " + first.split("TEST ", 1)[-1].split(" (")[0]
    if lo.startswith("step: fly") and "hauling your stock to" in lo:
        return "Hauling: fly to " + first.split("STEP: FLY to ", 1)[-1].split(" - ")[0].strip()
    if lo.startswith("step: deliver"):
        return "Deliver freelance job"
    if lo.startswith("step: accept freelance job -"):
        return "Accept freelance job " + first.split(" - ", 1)[-1].split(" (about")[0]
    if lo.startswith("step: accept freelance job"):
        return "Accept freelance job " + first.split(" - ", 1)[-1].split(" (about")[0]
    if lo.startswith("step: undock"):
        return "Undock and warp to a belt"
    if lo.startswith("step: show me a screen"):
        return "Show a screen " + first.split(" - ", 1)[-1].split(" (about")[0]
    if lo.startswith("step: air social goal"):
        return "AIR social goal " + first.split(" - ", 1)[-1].split(" (about")[0]
    if lo.startswith("step: fly to"):
        return "Fly to " + first.split("STEP: FLY to ", 1)[-1].split(" - ")[0].strip()
    if lo.startswith("step: buy at"):
        return "Trade: buy at " + first.split("STEP: BUY at ", 1)[-1].split(",")[0].strip()
    if lo.startswith("step: look around"):
        return "Look around " + first.split("LOOK AROUND ", 1)[-1].split(" (")[0].strip()
    if lo.startswith("step: haul"):
        return "Hauling stock to " + first.split(" to ", 1)[-1].split(" (")[0]
    if lo.startswith("step: upgrade gear"):
        return "Gear upgrade"
    if lo.startswith("step: show me the fitting window of your "):
        return "Fitting window " + first.split("window of your ", 1)[-1].split(" (")[0].strip()
    if lo.startswith("step: board your "):
        return "Board " + first.split("BOARD your ", 1)[-1].split(" (")[0].strip()
    if lo.startswith("step: fit "):
        return "Fit " + first.split("STEP: FIT ", 1)[-1].split(" to your")[0].strip()
    if lo.startswith("step: load "):
        return "Load " + first.split("STEP: LOAD ", 1)[-1].split(" into")[0].strip()
    if lo.startswith("step: pick up stock in "):
        return "Pick up stock " + first.split("STEP: PICK UP STOCK in ", 1)[-1].split(" (")[0].strip()
    if lo.startswith("step: acquire "):
        return "Acquire " + first.split("ACQUIRE ", 1)[-1].split(" - ")[0].strip()
    if lo.startswith("step: accept ") and "'s mission" in lo:
        return "Agent L1 accept " + first.split("ACCEPT ", 1)[-1].split("'S MISSION")[0].split("'s MISSION")[0].strip()
    if lo.startswith("step: do ") and "'s mission" in lo:
        return "Agent L1 do " + first.split("STEP: DO ", 1)[-1].split("'s MISSION")[0].strip()
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


THREADS = (("ISK: trading and hauling", ("best trade", "haul", "sell", "list")), ("AIR career and agent missions", ("air daily", "agent")),
           ("character growth: skills, ships, gear", ("test", "skill", "gear", "upgrade", "build")), ("teaching the model", ("update the model", "model")))


def _threads(cands):
    """The best candidate of each long-term thread -> {thread: (rate, label)}; a candidate that fits no thread goes under 'other'."""
    out = {}
    for rate, label, *_ in cands:
        low = label.lower()
        name = next((t for t, keys in THREADS if any(k in low for k in keys)), "other")
        r = 1e12 if rate == float("inf") else rate
        if name not in out or r > out[name][0]:
            out[name] = (r, label[:40])
    return out


def next_action(con, g, p, full=False, ahead=False):
    """KISS: ONE task or ONE chain of tasks that belong together, in order: sell stock here / list one item here, buy a skill book sold
    here, queue a skill, then the best agent mission (if it beats the best trade) else the best trade. `next` prints ONLY the first step;
    `next --plan` = the whole chain, why, and THE LONG VIEW; `next --all` = everything."""
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
            from .dailygoals import plan as _dg_plan
            _pl = _dg_plan(con, dg["reward_isk"], g=g, p=p)
            _rate = _pl["best"]["rate"] if _pl["best"] else dg["reward_isk"] * 60.0 / dg.get("minutes_estimate", 20)
            cands.append((_rate, "AIR daily goals", daily_goal_step(dg, con, g=g, p=p, compact=not ahead), "once a day"))
    except Exception:                                            # noqa: BLE001
        pass
    try:                                                         # a screen the model still needs (screens_wanted.json): asked once each, one at a time
        from .screens import wanted_candidate as _wc
        _w = _wc(con, g, p)
        if _w:
            cands.append((_w[0], "show me a screen", _w[1], "the model needs it"))
    except Exception:                                            # noqa: BLE001
        pass
    try:                                                         # a freelance delivery job paid from stock you hold here: accept, fly, deliver
        from .jobchain import candidate as _jc
        _j = _jc(con, g, p)
        if _j:
            cands.append((_j[0], "freelance job delivery", _j[1], "from stock, more than selling"))
    except Exception:                                            # noqa: BLE001
        pass
    try:                                                         # AIR Social goals: 25,000 ISK + 10 career points for a one-minute click task
        from .social import candidate as _soc
        from .progress import values as _vals
        _v = _vals()
        _sc = _soc(con, 25000.0 + 10 * float(_v.get("career_point_isk", 0)))
        if _sc:
            cands.append((_sc[0], "AIR social goal", _sc[1], "25,000 ISK + 10 career points each"))
    except Exception:                                            # noqa: BLE001
        pass
    try:                                                         # screenshots the tool needs from the game: a short step now and then (data makes later steps better)
        from . import screens as _sc
        if _sc.due(con) and daily_goal_program() is not None:
            cands.append((_sc.rate(), "update the model from the game", _sc.step(con), "once a day (every 12 h)"))
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
        cands.append((rate_adj, "agent mission", (agent if ahead or not AGENT_FIRST["text"] else AGENT_FIRST["text"]),
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
    hc = None
    try:
        from .haulchain import candidate as _hc
        hc = _hc(con, g, p)                                      # a haul already under way (cargo is invisible to sync, so it is remembered)
    except Exception:                                            # noqa: BLE001
        hc = None
    if hc:
        _st = None
        try:
            from .haulchain import load as _hl
            _st = _hl(con)
        except Exception:                                        # noqa: BLE001
            pass
        cands.append((hc[0], f"haul stock to {(_st or {}).get('dest', '?')} (under way)", hc[1], "re-planned at every stop; keeps going unless something pays 25% more"))
    elif h:
        h_rate = h["rate_hr"]
        try:                                                     # gear you need anyway that is cheaper on the route is part of what the trip earns
            from .tripplus import needs_saving
            sv = needs_saving(con, g, p, h["dest"])
            if sv > 0 and h.get("minutes"):
                h_rate = (h["gain"] + sv) * 60.0 / h["minutes"]
        except Exception:                                        # noqa: BLE001
            pass
        cands.append((h_rate, f"haul stock to {h['dest']}", haul_step(h, g, p, con), "sell-now prices at the far market"))
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
    try:                                                         # a haul that wins starts a chain: from now on it is planned one jump at a time
        if cands and cands[0][1].startswith("haul stock to ") and "(under way)" not in cands[0][1] and h:
            from .haulchain import make as _hmake, save as _hsave
            _hsave(con, _hmake(h, p.current_system))
    except Exception:                                            # noqa: BLE001
        pass
    try:                                                         # a trade whose BUY step wins: from now on the cargo is flown on one jump at a time
        if cands:
            from .tradestep import pending as _pend
            _h = _pend(cands[0][2])
            if _h:
                from .haulchain import make as _hmake2, save as _hsave2
                _hsave2(con, _hmake2(_h, p.current_system))
    except Exception:                                            # noqa: BLE001
        pass
    try:                                                         # every trip gets the same extras: agents on the route, cheap things you need, trades both ways
        from .tripplus import extras as _extras
        dest_ = None
        if cands and cands[0][1].startswith("haul stock to ") and h:
            dest_ = h["dest"]
        if dest_:
            ex_ = _extras(con, g, p, dest_)
            keep_lines = [l for l in ex_["lines"] if not l.startswith(("going:", "coming back:", "trades there"))] if h.get("extra_lines") else ex_["lines"]
            if keep_lines:
                c0 = cands[0]
                cands[0] = (c0[0], c0[1], c0[2] + "\n   ALSO ON THE ROUTE:\n" + "\n".join("      " + l for l in keep_lines), c0[3])
    except Exception:                                            # noqa: BLE001
        pass
    why = ""
    exp_note = ""
    try:                                                         # UNMODELED activities compete on equal footing: expected ISK/hr (prior x risk + value of information, set-up spread over 5 runs)
        from .catalog import covered_by_offers, equal_footing, experiment_step
        from . import combatprep
        _hop = _hop_step(g, p, con)
        best_known = min(max((c[0] for c in cands), default=0.0), 5_000_000.0)      # a near-zero-minute step gives absurd ISK/hr: cap it
        haul_on = False
        try:                                                     # a haul under way (cargo to deliver / sell) is never interrupted by a test
            from .haulchain import load as _hload
            haul_on = bool(_hload(con))
        except Exception:                                        # noqa: BLE001
            pass

        def _prep(a_):
            return combatprep.prep_estimate(con, g, p) if a_["id"] in ("agent_l1_security", "agent_l2_security", "ratting") else (0.0, 0.0)

        def _test_step(act, reason):
            step_txt = experiment_step(act, reason)
            if act["id"] in ("agent_l1_security", "agent_l2_security", "ratting"):       # a combat test is only valid with a combat-ready ship: the step is the first missing piece
                step_txt = combatprep.next_step(con, g, p, _hop) or combatprep.agent_step(g, p, _hop) or step_txt
            if act["id"] == "station_trading":                    # never point at `next` itself: show the actual best trade
                step_txt = None
                opps_ = plan(con, p, 5, False)
                from .tradestep import fresh as _fresh
                opps_ = [x for x in (_fresh(con, g, p, y) if y.kind == "trade" else y for y in opps_[:3]) if x]      # live check of the item before it is offered
                if opps_ and opps_[0].kind == "trade":
                    from .tradestep import trade_step as _ts
                    step_txt = _ts(con, g, p, opps_[0])
                    if step_txt:
                        step_txt += "\n   Unmodeled: 3 timed runs turn the guess into your own number."
            if step_txt and step_txt.lstrip().startswith("STEP: FLY to") and act["id"] not in ("agent_l1_security", "agent_l2_security", "ratting"):
                step_txt = None                                   # a test that only sends you travelling for a guessed gain is not offered
            return step_txt

        if not haul_on:
            for item in equal_footing(con, p.wallet_isk, best_known, here=p.current_system, covered=covered_by_offers(), extra_cost=_prep)[:3]:
                act = item["act"]
                try:
                    txt = _test_step(act, "never timed")
                except Exception:                                # noqa: BLE001
                    txt = None
                if not txt:
                    continue
                note = (f"unmodeled: prior {act['prior'][0]:,.0f}-{act['prior'][1]:,.0f} ISK/hr, risk {act.get('risk', 'low')}"
                        + (f", about {item['prep_min']:.0f} min of set-up first" if item["prep_min"] else "") + "; timing it teaches the model")
                cands.append((item["eff"], f"test {act['name']}", txt, note))
        cands.sort(key=lambda c: -c[0])
        try:                                                     # no flip-flop: stay on the plan you were on unless another one is clearly (15%) better
            import json as _jj
            _r = con.execute("SELECT value FROM meta WHERE key='last_plan'").fetchone()
            _last = (_jj.loads(_r[0]) if _r else {}).get("label")
            if _last and cands and cands[0][1] != _last:
                _i = next((i for i, c in enumerate(cands) if c[1] == _last), None)
                if _i is not None and cands[0][0] < cands[_i][0] * 1.15 and cands[0][0] != float("inf"):
                    cands.insert(0, cands.pop(_i))
            if cands:
                con.execute("INSERT OR REPLACE INTO meta VALUES('last_plan', ?)", (_jj.dumps({"label": cands[0][1]}),))
        except Exception:                                        # noqa: BLE001
            pass
        con.commit()
    except Exception:                                            # noqa: BLE001
        pass
    long_view = ""
    try:                                                         # LOOK AHEAD: what pays most over the next hours, and which free enabler to queue now
        from .lookahead import analyse, enabler_step, format_long_view
        an_ = analyse(con, g, p, cands)
        long_view = format_long_view(an_)
        if an_["enabler"]:
            steps = [x for x in steps if not x.startswith("STEP: QUEUE A SKILL")]
            steps.append(enabler_step(an_["enabler"], an_["base"]))
    except Exception:                                            # noqa: BLE001
        long_view = ""
    if KEEP_NOTES:
        kn = "STOCK HERE I AM NOT SELLING (on purpose):\n" + "\n".join(KEEP_NOTES)
        long_view = (long_view + "\n\n" + kn) if long_view else kn
    try:                                                         # standing purchase goal: what to buy to make combat possible (plan view only)
        from .combatgoal import format_goal
        cg = format_goal(con)
        long_view = (long_view + "\n\n" + cg) if (long_view and cg) else (long_view or cg)
    except Exception:                                            # noqa: BLE001
        pass
    try:                                                         # NO PING-PONG: a first step that flies straight back to the system you just left must be clearly better than the best step that does not
        import re as _re
        from .livepos import reversal as _rev
        _FLY = _re.compile(r"STEP: FLY to ([^\n]+?)(?: - |$|\n)")

        def _flip(c):
            m = _FLY.search(c[2] or "")
            return _rev(con, m.group(1).strip(), p.current_system) if m else 0
        if cands and _flip(cands[0]):
            lvl = _flip(cands[0])
            alt = next((i for i, c in enumerate(cands[1:], 1) if not _flip(c)), None)
            need = 2.0 if lvl == 2 else 1.5                      # a loop already under way needs to be twice as good to go back again
            if alt is not None and cands[0][0] < cands[alt][0] * need:
                cands.insert(0, cands.pop(alt))
            elif alt is None or cands[0][0] >= cands[alt][0] * need:
                cands[0] = (cands[0][0], cands[0][1], (cands[0][2] or "") + f"\n   (going back to where you just came from: it is still the best plan by {need:g}x, but check it is worth the trip)", cands[0][3])
    except Exception:                                            # noqa: BLE001
        pass
    plans_txt = ""
    if cands:                                                    # every plan on ONE list, best ISK/hr first, each with the step it would take next
        def _first(t):
            for ln in (t or "").split("\n"):
                if ln.strip().startswith(("STEP:", "AGENT MISSION")):
                    return ln.strip()[:110]
            return (t or "").strip().split("\n", 1)[0][:110]
        plans_txt = "ALL PLANS, best ISK/hr first (agents, skills, freelance, trades, hauls, goals and unmodeled activities on the same footing; the top one is your next step):\n" + "\n".join(
            f"   {i}. {c[0]:>10,.0f} ISK/hr  {c[1]}  ->  {_first(c[2])}" for i, c in enumerate(cands[:10], 1))
    if cands:
        steps.append(cands[0][2])
        trade_text = cands[0][2] if cands[0][1].startswith("best trade") else None
        if len(cands) > 1:
            why = "WHY THIS ONE (ISK per hour, same yardstick for all): " + "; ".join(
                f"{'>> ' if i == 0 else ''}{c[1]} " + ("(model turn)" if c[0] == float("inf") else f"{c[0]:,.0f}") for i, c in enumerate(cands[:5]))
            why += "   (cash + the value of progress and of teaching the model; numbers editable in progress_values.json)"
            why += "\nTHREADS (every stop re-ranks all of them; the best one wins, none is dropped): " + "; ".join(
                f"{t}: {lbl} {r:,.0f}" for t, (r, lbl) in _threads(cands).items())
    if trade_text:
        steps.append(trade_text.rsplit("\n" + AFTER, 1)[0])
    if selling or trade_text:
        from .bonus import market_lines
        bl = market_lines()
        if bl:
            steps[0 if selling else -1] += "\n" + "\n".join(bl)
    try:
        from .agentchain import mark_shown as _ams
        _ams(con, steps[0] if steps else "")
        from .jobchain import mark_shown as _jms
        _jms(con, steps[0] if steps else "")
        from .social import mark_shown as _ms
        from .screens import wanted_mark_shown as _wms
        _ms(con, steps[0] if steps else "")
        _wms(con, steps[0] if steps else "", g, p)
    except Exception:                                            # noqa: BLE001
        pass
    steps = [x if x.startswith("AGENT MISSION") else x + "\n" + _timer(_name_of(x), con) for x in steps]
    if not ahead:                                                # KISS: ONE step at a time; look ahead only when asked
        first = steps[0]
        from .miningchain import prestep as _mp
        first = _mp(con, g, p, first)                                                                    # accept jobs, fly, undock before the mining itself
        first = "\n".join(l for l in first.split("\n") if not l.startswith("   LATER:"))       # future steps belong in --plan, not in this one
        if first.startswith("STEP: FLY to") and "hauling your stock to" in first:
            from .haul import hop_only
            first = hop_only(first, p.current_system)
        out = finish_block(first)
        out += "\n\n(look ahead: python -m eve_profit next --plan   |   everything: python -m eve_profit next --all)"
        return out + home
    out = _chain(steps) + (("\n\n" + exp_note) if exp_note else "") + (("\n\n" + plans_txt) if plans_txt else "") + (("\n\n" + why) if why else "") + (("\n\n" + long_view) if long_view else "") + "\n\n" + DONE
    out += "\n(everything: python -m eve_profit next --all)"
    return out + home
