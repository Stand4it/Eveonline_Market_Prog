"""AIR Daily Goals planner: the reward (445,000 ISK seen) is paid for ANY 2 of the 5 daily goals, so pick the cheapest pair.
Every goal is costed in minutes (travel included) and ISK to get it done; jumps are free when the trip is going there anyway.
Numbers marked '?' are guesses: edit the "plan" block of a goal in bonus_programs.json (minutes, cash, feasible, why_not) after you time one."""
import itertools

PER_JUMP_MIN = 3.0           # minutes per jump (same as agent_offers.json min_per_jump)
JUMPS_FREE_MIN = 1.0         # extra minutes the 3-jump goal costs when you are travelling that far anyway

GUN_WORDS = ("blaster", "autocannon", "railgun", "laser", "artillery", "launcher", "pulse", "beam")
SKIP_WORDS = ("probe", "mining", "salvag", "cargo scanner", "survey", "tractor", "analyzer")


def _q(con, sql, args=()):
    try:
        return con.execute(sql, args).fetchall()
    except Exception:                                                   # noqa: BLE001
        return []


def _fitted_names(con):
    return [(r[0] or "").lower() for r in _q(con, "SELECT t.name FROM fitted f JOIN types t ON t.type_id=f.type_id")]


def _min_ask(con, name):
    r = _q(con, "SELECT MIN(o.price) FROM orders o JOIN types t ON t.type_id=o.type_id WHERE t.name=? COLLATE NOCASE AND o.is_buy=0", (name,))
    return float(r[0][0]) if r and r[0][0] else None


def _has_skill(con, name):
    r = _q(con, "SELECT s.level FROM character_skills s JOIN types t ON t.type_id=s.skill_id WHERE t.name=? COLLATE NOCASE", (name,))
    return bool(r and r[0][0] >= 1)


COUNT_TRADES = False         # side trades are shown but NOT counted in the goal's rate: one-unit 200% margins are usually traps (check each first)
TRADE_HAIRCUT = 0.5          # count only half of side-trade profit (prices move, thin orders vanish): same as haul.py


def _trades(con, g, p, dest, m3=0.0):
    """Trades worth doing on the way to `dest` and back with the spare hold: (ISK after haircut, extra minutes, lines)."""
    if g is None or p is None or not dest:
        return 0.0, 0.0, []
    try:
        from .nextstep import trade_extras
        isk, mins, lines = trade_extras(con, g, p, {"to_system": dest, "m3": m3})
    except Exception:                                                   # noqa: BLE001
        return 0.0, 0.0, []
    return isk * TRADE_HAIRCUT, mins, lines


def _far_places(con, mining=None, offers=None):
    """Known places 3+ jumps away that are worth going to anyway: (rate or 0, label, jumps)."""
    out = []
    try:
        from .nextstep import offers_rows
        for rate, net, minutes, o, tags in offers if offers is not None else offers_rows(con):
            if o.get("jumps", 0) >= 3:
                out.append((rate, f"{o['agent']} (agent mission, {o['jumps']} jumps)", o["jumps"], o.get("agent_system")))
    except Exception:                                                   # noqa: BLE001
        pass
    try:
        from .mining_sites import rank_sites
        for s in mining if mining is not None else rank_sites(con):
            if s["jumps"] >= 3:
                out.append((0.0, f"{s['system']} (mining, {s['jumps']} jumps)", s["jumps"], s["system"]))
    except Exception:                                                   # noqa: BLE001
        pass
    out.sort(key=lambda x: -x[0])
    return out


def build_option(con, g=None, p=None, free=None):
    """The best build to start from where you stand (make-or-buy, with what it is worth afterwards). Without a map: the plain cheapest build."""
    if g is not None and p is not None:
        try:
            from .makebuy import describe, options as mb
            res = mb(con, g, p, free=free)
            if res:
                o = res[0]
                t_isk, t_min, t_lines = _trades(con, g, p, o.get("trip_to"), o.get("m3", 0.0))
                if not COUNT_TRADES:
                    t_cnt_isk, t_cnt_min = 0.0, 0.0
                else:
                    t_cnt_isk, t_cnt_min = t_isk, t_min
                how = describe(o)
                if t_isk > 0:
                    how += (f"\n   SIDE TRADES on the trip to {o['trip_to']} and back: ~{t_isk:,.0f} ISK (half counted; "
                            + ("counted in the rate" if COUNT_TRADES else "NOT counted in the rate: confirm each with `check`, a huge margin on one unit is often a trap") + ")\n      "
                            + "\n      ".join(t_lines))
                return {"goal": "Manufacture an Item", "ok": True, "minutes": o["minutes"] + t_cnt_min, "cash": -(o["net"] + t_cnt_isk), "jumps_away": 0, "job_min": o.get("job_min", 0.0),
                        "how": how, "mb": o}
        except Exception:                                               # noqa: BLE001
            pass
    best = None
    for bp, name in _q(con, "SELECT b.blueprint_id, t.name FROM my_blueprints b LEFT JOIN types t ON t.type_id=b.blueprint_id"):
        mats = _q(con, "SELECT m.material_id, m.quantity, t.name FROM bp_materials m LEFT JOIN types t ON t.type_id=m.material_id WHERE m.blueprint_id=?", (bp,))
        if not mats:
            continue
        cash, missing, buy_lines = 0.0, False, []
        for mid, qty, mname in mats:
            have = _q(con, "SELECT COALESCE(SUM(quantity),0) FROM inventory WHERE type_id=?", (mid,))[0][0]
            need = max(0, qty - have)
            if need:
                ask = _min_ask(con, mname or "")
                if ask is None:
                    missing = True
                    break
                cash += ask * need
                buy_lines.append(f"{need:,} x {mname}")
        if missing:
            continue
        if best is None or cash < best["cash"]:
            best = {"cash": cash, "bp": name or str(bp), "buy": buy_lines}
    if not best:
        return {"goal": "Manufacture an Item", "ok": False, "why_not": "no blueprint you own can be built from materials on the scanned market", "minutes": 0, "cash": 0}
    minutes = 4.0 + (4.0 if best["buy"] else 0.0)
    how = f"Industry > build 1 run of {best['bp']}" + (" (buy first: " + ", ".join(best["buy"]) + ")" if best["buy"] else " (all materials already in your hangar)")
    return {"goal": "Manufacture an Item", "ok": True, "minutes": minutes, "cash": best["cash"], "how": how, "jumps_away": 0}


def scan_option(con):
    fitted = _fitted_names(con)
    launcher = any("probe launcher" in n for n in fitted)
    skill = _has_skill(con, "Astrometrics")
    if not skill:
        return {"goal": "Scan 5 Signatures", "ok": False, "why_not": "needs the Astrometrics skill (train I, about 5 min of queue)", "minutes": 0, "cash": 0}
    probes = (_min_ask(con, "Core Scanner Probe I") or 15000.0) * 8
    cash = probes if launcher else probes + 150000.0
    how = "fit a Probe Launcher and 8 probes in your Imicus" if not launcher else "scan down 5 signatures in Rotonos or next door"
    return {"goal": "Scan 5 Signatures", "ok": True, "minutes": 25.0 if launcher else 35.0, "cash": cash, "how": how + "  (?)", "jumps_away": 0}


def destroy_option(con):
    fitted = _fitted_names(con)
    guns = [n for n in fitted if any(w in n for w in GUN_WORDS) and not any(w in n for w in SKIP_WORDS)]
    try:
        from .mining_sites import sites
        rat = sorted([s for s in sites() if s.get("sec", 0) >= 0.5 and s.get("hostiles") not in (None, "", "?", "unknown")], key=lambda s: s["jumps"])
    except Exception:                                                   # noqa: BLE001
        rat = []
    jumps = rat[0]["jumps"] if rat else 4
    where = f"{rat[0]['system']} ({rat[0]['hostiles']} rats, {jumps} jumps)" if rat else f"a system with rats ({jumps} jumps?)"
    minutes = 40.0 + 2 * jumps * PER_JUMP_MIN
    if guns:
        return {"goal": "Destroy 25 non-capsuleers", "ok": True, "minutes": minutes, "cash": 20000.0,
                "how": f"fly to {where} and kill 25 rats with your fitted guns (ammo ~20k)  (?)", "jumps_away": jumps}
    return {"goal": "Destroy 25 non-capsuleers", "ok": True, "minutes": minutes + 20, "cash": 120000.0,
            "how": f"you have no guns fitted: buy guns + ammo (~120k?), then fly to {where} and kill 25 rats  (?)", "jumps_away": jumps}


def repair_option(con):
    return {"goal": "Armor Repair other Capsuleers", "ok": False, "minutes": 0, "cash": 0,
            "why_not": "needs a remote armor repairer AND other players in a fleet to repair 2,500: not solo, not routed"}


def _route_ids(g, p, sysname):
    """System ids on the safe route from where you are to sysname (they are 'free' shopping stops while you travel anyway)."""
    if g is None or p is None or not sysname:
        return set()
    try:
        r = g.route(g.id_of(p.current_system), g.id_of(sysname), 60, p.avoid_yellow)
        return set(r.path) if r else set()
    except Exception:                                                   # noqa: BLE001
        return set()


def jumps_option(con, places=None, g=None, p=None, idx=0):
    places = _far_places(con) if places is None else places
    pl = places[idx] if places and idx < len(places) else None
    dest = pl[1] if pl else "Manifest (epic arc agent, 3 jumps)"
    sysname = pl[3] if pl and len(pl) > 3 else ("Manifest" if not places else None)
    t_isk, t_min, t_lines = _trades(con, g, p, sysname)
    how = f"fly to {dest}: that trip IS the 3 jumps (stay in 0.5+ space)"
    if t_isk > 0:
        how += (f"\n      side trades on the way there and back: ~{t_isk:,.0f} ISK (half counted; " + ("counted in the rate" if COUNT_TRADES else "NOT counted in the rate: confirm each with `check`, a huge margin on one unit is often a trap")
                + ")\n         " + "\n         ".join(t_lines))
    if not COUNT_TRADES:
        t_isk, t_min = 0.0, 0.0
    try:                                                                # agents on the route and cheap things you need anyway
        from .tripplus import _agents, _route, cheap_needs
        path = _route(g, p, sysname)
        more = _agents(g, path) + cheap_needs(con, g, p, path) if path else []
        if more:
            how += "\n      also on that route:\n         " + "\n         ".join(more)
    except Exception:                                                   # noqa: BLE001
        pass
    return {"goal": "Complete 3 Jumps", "ok": True, "minutes": 3 * PER_JUMP_MIN + t_min, "cash": -t_isk, "jumps_away": 0,
            "how": how, "dest": dest, "dest_system": sysname}


def options(con, places=None, g=None, p=None, idx=0):
    jumps = jumps_option(con, places, g, p, idx)
    build = build_option(con, g, p)
    route = _route_ids(g, p, jumps.get("dest_system"))
    if route and build.get("ok"):                                       # the same build when you shop on the jumps trip you are making anyway
        build["with_jumps"] = build_option(con, g, p, free=route)
    return [jumps, build, scan_option(con), destroy_option(con), repair_option(con)]


def plan(con, reward=445000.0, free_ride=False, places=None, g=None, p=None):
    """Best pair of goals by net ISK per hour. free_ride=True when your next task already goes 3+ jumps.
    Tries the top few far destinations for the 3 jumps: shopping for the build on the way there is free."""
    places = _far_places(con) if places is None else places
    if not any(pl[3:4] == ("Manifest",) for pl in places):
        places = list(places) + [(0.0, "Manifest (epic arc agent Cassandra Ahfrim, 3 jumps)", 3, "Manifest")]
    best, first_opts = None, None
    for idx in range(min(3, len(places))):
        opts = options(con, places, g, p, idx)
        first_opts = first_opts or opts
        ok = [o for o in opts if o["ok"]]
        for a, b in itertools.combinations(ok, 2):
            for x, y in ((a, b), (b, a)):                               # shopping on the jumps trip costs no extra travel
                if x["goal"] == "Complete 3 Jumps" and y["goal"] == "Manufacture an Item" and y.get("with_jumps"):
                    a, b = (x, y["with_jumps"]) if x is a else (y["with_jumps"], x)
                    break
            minutes = a["minutes"] + b["minutes"]
            for x, y in ((a, b), (b, a)):                               # jumps are free when the other goal's trip goes 3+ jumps anyway
                if x["goal"] == "Complete 3 Jumps" and (y.get("jumps_away", 0) >= 3 or free_ride):
                    minutes = y["minutes"] + JUMPS_FREE_MIN
            cash = a["cash"] + b["cash"]
            rate = (reward - cash) * 60.0 / max(minutes, 1.0)
            if best is None or rate > best["rate"]:
                jobber = a if a.get("job_min", 0.0) >= b.get("job_min", 0.0) else b
                clock = max(minutes, jobber["minutes"] + jobber.get("job_min", 0.0))      # the job runs in the background while you do the other goal
                best = {"pair": (a, b), "minutes": minutes, "cash": cash, "rate": rate, "net": reward - cash, "clock": clock}
    opts = first_opts or []
    if best:                                                            # the table lists the options of the winning plan
        names = {o["goal"] for o in best["pair"]}
        opts = [next((o for o in best["pair"] if o["goal"] == x["goal"]), x) for x in opts]
    return {"best": best, "options": opts, "reward": reward}


def _clean(line):
    return " ".join(line.split())


def compact_plan(pl, progress=None):
    """ONE task as a short ordered checklist (the default `next`): what to do, in order. The pair analysis, the table of all five goals and
    the side trades stay in `next --plan`."""
    b = pl["best"]
    if not b:
        return "STEP: AIR DAILY GOALS - no pair of goals is doable right now (see `next --plan`)"
    a1, a2 = b["pair"]
    names = " + ".join(o["goal"] for o in sorted(b["pair"], key=lambda o: o["goal"] != "Complete 3 Jumps"))
    L = [f"STEP: AIR DAILY GOALS - about {pl['reward']:,.0f} ISK for 2 of the 5 goals ({names}), ~{b['minutes']:.0f} min, ~{max(b['cash'], 0):,.0f} ISK to do it", ""]
    jumps = next((o for o in b["pair"] if o["goal"] == "Complete 3 Jumps"), None)
    build = next((o for o in b["pair"] if o["goal"] == "Manufacture an Item" and o.get("mb")), None)
    steps = []
    if jumps and build:
        mb = build["mb"]
        route_buys = [x for x in mb["buy"] if "(on your route)" in x]
        home_buys = [x for x in mb["buy"] if "(on your route)" not in x]
        dest = jumps.get("dest", "the far system")
        if route_buys and not home_buys:
            steps.append((f"Fly to {dest}: that trip is Complete 3 Jumps. On the way, buy:", [_clean(x) for x in route_buys]))
            steps.append((f"Back at your station: Industry > start {mb['product']} ({mb['runs']} run{'s' if mb['runs'] != 1 else ''}, {mb['units']} items); the job runs ~{mb.get('job_min', 0):.0f} min", []))
        else:
            if mb["buy"]:
                steps.append(("Buy first:", [_clean(x) for x in mb["buy"]]))
            steps.append((f"Industry > start {mb['product']} ({mb['runs']} run{'s' if mb['runs'] != 1 else ''}, {mb['units']} items); the job runs ~{mb.get('job_min', 0):.0f} min in the background", []))
            steps.append((f"While it runs, fly to {dest}: that trip is Complete 3 Jumps (stay in 0.5+ space)", []))
        steps.append(("Collect the finished job in Industry: that is Manufacture an Item", []))
    else:
        for o in b["pair"]:
            steps.append((f"{o['goal']}: " + o["how"].split("\n")[0].strip(), []))
    steps.append(("Open Opportunities > AIR Daily Goals: both goals should show complete, then stop the timer", []))
    for n, (txt, subs) in enumerate(steps, 1):
        L.append(f"   {n}. {txt}")
        L += [f"        {x}" for x in subs]
    L += ["", "   (the pair analysis, all five goals and the side trades: next --plan)"]
    return "\n".join(L)


def _indent(text, pad):
    return "\n".join(pad + l if i else l for i, l in enumerate(text.split("\n")))


def format_plan(pl, progress=None):
    progress = progress or {}
    b = pl["best"]
    if not b:
        return "STEP: AIR DAILY GOALS - no pair of goals is doable right now (see the list below)"
    pair = sorted(b["pair"], key=lambda o: -o.get("job_min", 0.0))      # the one with a background job goes first
    L = [f"STEP: AIR DAILY GOALS - about {pl['reward']:,.0f} ISK for any 2 of the 5 goals (resets daily)", "",
         f"   BEST PAIR  {pair[0]['goal']} + {pair[1]['goal']}",
         f"      {b['minutes']:.0f} min of your time (~{b.get('clock', b['minutes']):.0f} min on the clock)   {b['cash']:,.0f} ISK to do it   = {b['rate']:,.0f} ISK/hr", ""]
    for n, o in enumerate(pair, 1):
        L.append(f"   {n}. {o['goal']} ({progress.get(o['goal'], '').strip() or '-'})")
        L.append("      " + _indent(o["how"], "   "))
        L.append("")
    L.append("   ALL FIVE                         your minutes     ISK to do it")
    for o in sorted(pl["options"], key=lambda o: (not o["ok"], o["minutes"])):
        mark = ">>" if o in b["pair"] else "  "
        if o["ok"]:
            c = round(o["cash"]) + 0.0
            L.append(f"   {mark} {o['goal']:<30} {o['minutes']:>6.0f} min     " + (f"{c:>10,.0f}" if c >= 0 else f"pays back +{-c:,.0f}"))
        else:
            L.append(f"      {o['goal']:<30} NOT ROUTED: {o['why_not']}")
    L.append("")
    L.append("   Check Opportunities > AIR Daily Goals in game. (?) = a guess: time it and the model learns.")
    return "\n".join(L)


# ---------------------------------------------------------------------------------------------------------------------------------------
# THE CHAIN: the daily goals as ONE STEP AT A TIME. The tool remembers the plan (meta 'daily_chain') and works out which step you are on from
# what `sync` sees: where you are, what is in your hangar, whether a build job is running. `next` shows only that step.
# Steps: buy at home -> fly there (the 3 jumps) -> buy there -> [epic arc, optional] -> fly home -> start the build -> wait and collect -> done.
# ---------------------------------------------------------------------------------------------------------------------------------------
import json as _json
import time as _time

CHAIN_KEY = "daily_chain"
CHAIN_MAX_AGE_S = 36 * 3600


def _chain_load(con):
    try:
        r = con.execute("SELECT value FROM meta WHERE key=?", (CHAIN_KEY,)).fetchone()
        st = _json.loads(r[0]) if r else None
    except Exception:                                                   # noqa: BLE001
        return None
    if st and _time.time() - st.get("t", 0) > CHAIN_MAX_AGE_S:
        return None
    return st


def _chain_save(con, st):
    con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (CHAIN_KEY, _json.dumps(st)))
    con.commit()


def chain_clear(con):
    try:
        con.execute("DELETE FROM meta WHERE key=?", (CHAIN_KEY,))
        con.commit()
    except Exception:                                                   # noqa: BLE001
        pass


def chain_done(con, changed=None):
    """`done`: mark the current optional step (the epic arc at the far system) as finished or skipped. -> message."""
    try:
        from .miningchain import job_done
        m = job_done(con)
        if m:
            return m
    except Exception:                                                   # noqa: BLE001
        pass
    try:
        from .screens import wanted_done
        m = wanted_done(con, changed)
        if m:
            return m
    except Exception:                                                   # noqa: BLE001
        pass
    try:
        from .social import done as _social_done
        m = _social_done(con)
        if m:
            return m
    except Exception:                                                   # noqa: BLE001
        pass
    try:
        from .screens import advance, due
        if due(con):                                                    # the game-screens step is the one on screen: that screen was sent, on to the next
            return advance(con)
    except Exception:                                                   # noqa: BLE001
        pass
    st = _chain_load(con)
    if st:
        st["epic_done"] = True
        _chain_save(con, st)
    return "OK, that step is marked done. Run  python -m eve_profit next  for the next one."


def _chain_from_plan(pl, here):
    """Start a chain from the best plan when it is the jumps + build pair; None otherwise."""
    b = pl.get("best")
    if not b:
        return None
    jumps = next((o for o in b["pair"] if o["goal"] == "Complete 3 Jumps"), None)
    build = next((o for o in b["pair"] if o["goal"] == "Manufacture an Item" and o.get("mb")), None)
    if not (jumps and build):
        return None
    mb = build["mb"]
    return {"t": _time.time(), "home": here, "dest": jumps.get("dest_system") or "", "dest_label": jumps.get("dest", ""), "product": mb["product"], "runs": mb["runs"],
            "units": mb["units"], "job_min": mb.get("job_min", 0.0), "buy": mb.get("buy_items", []), "bought": False, "started": False, "epic_done": False,
            "reward": pl.get("reward", 445000.0), "minutes": b["minutes"]}


def _held(con, item, system_name, g):
    """Units of `item` in your hangar in that system."""
    try:
        sid = g.id_of(system_name)
        r = con.execute("SELECT COALESCE(SUM(i.quantity),0) FROM inventory i JOIN types t ON t.type_id=i.type_id WHERE t.name=? COLLATE NOCASE AND i.system_id=?", (item, sid)).fetchone()
        return int(r[0] or 0)
    except Exception:                                                   # noqa: BLE001
        return 0


def _station_of(con, g, item, system_name):
    """Station with the cheapest sell order for the item in that system: 'Manifest V - AIR Laboratories Trade Center'."""
    try:
        r = con.execute("SELECT s.name FROM orders o LEFT JOIN stations s ON s.station_id=o.location_id JOIN types t ON t.type_id=o.type_id "
                        "WHERE t.name=? COLLATE NOCASE AND o.is_buy=0 AND o.system_id=? ORDER BY o.price ASC LIMIT 1", (item, g.id_of(system_name))).fetchone()
        return r[0] if r and r[0] else ""
    except Exception:                                                   # noqa: BLE001
        return ""


def way_lines(res, wallet, max_lines=4, hold_fn=None):
    """Lines for what is worth buying, selling or carrying on the way: stock from your hangar sold at a stop, and trades (buy at one stop,
    sell at a later one) that pass a sanity check: margin under 100% (one-unit 200% margins are usually traps) and under 30% of your wallet."""
    buys, sells = {}, {}
    for sysname, detour, acts in res.get("stops", []):
        for nm, q, c in acts.get("buy", []):
            buys.setdefault(nm, []).append((sysname, q, c))
        for nm, q, r in acts.get("sell", []):
            sells.setdefault(nm, []).append((sysname, q, r))
    lines = []
    for nm, bl in buys.items():
        for a, q, c in bl:
            for b, q2, r in sells.get(nm, []):
                if b == a or not q or not q2:
                    continue
                u = min(q, q2)
                cost, rev = c * u / q, r * u / q2
                if cost <= 0 or rev / cost - 1 > 1.0 or cost > 0.3 * wallet or rev - cost < 10000:
                    continue
                lines.append((rev - cost, f"buy {u:,} x {nm} at {a} (-{cost:,.0f}), sell at {b} (+{rev:,.0f}) = +{rev - cost:,.0f} ISK"))
    keeps = []
    for nm, sl in sells.items():
        if nm in buys:
            continue
        for b, q, r in sl:
            adv = hold_fn(nm, q, r) if hold_fn else None
            if adv:                                                  # a far market pays several times more: keep it, do not sell cheap on the way
                from .worldprices import keep_line
                keeps.append(keep_line(nm, q, adv))
            elif r >= 10000:
                lines.append((r, f"sell {q:,} x {nm} from your hangar at {b} (+{r:,.0f})"))
    lines.sort(key=lambda x: -x[0])
    return keeps + [x[1] for x in lines[:max_lines]]


def _on_the_way(con, g, p, dest):
    try:
        import dataclasses
        from .journey import plan_journey
        res = plan_journey(con, g, dataclasses.replace(p, wallet_isk=0.3 * (p.wallet_isk or 0) + 1), dest, detour=1)
        stacks = {}
        for r in con.execute("SELECT i.type_id, i.quantity, t.name, t.volume FROM inventory i JOIN types t ON t.type_id=i.type_id WHERE i.system_id=?", (g.id_of(p.current_system),)):
            stacks[r["name"]] = (r["type_id"], r["quantity"], r["volume"] or 0.0)

        def hold_fn(name, qty, local_net):
            from .worldprices import hold_advice
            if name not in stacks:
                return None
            tid, have, vol = stacks[name]
            return hold_advice(con, tid, min(qty, have), vol, local_net)
        return way_lines(res, p.wallet_isk or 0, hold_fn=hold_fn)
    except Exception:                                                   # noqa: BLE001
        return []


def chain_step(con, g, p, pl, reward_ok=True):
    """The ONE step the daily goals chain is at right now, or None when the chain does not apply (then the caller shows the plain checklist)."""
    st = _chain_load(con)
    if st is None:
        st = _chain_from_plan(pl, p.current_system)
        if st is None:
            return None
    here = p.current_system
    home, dest = st["home"], st["dest"] or st["home"]
    far = [x for x in st["buy"] if x["system"] != home]
    near = [x for x in st["buy"] if x["system"] == home]
    slots_used = int(getattr(p, "mfg_slots_used", 0) or 0)
    changed = False
    head = f"STEP: AIR DAILY GOALS - about {st['reward']:,.0f} ISK for 2 of the 5 goals (Complete 3 Jumps + Manufacture an Item)"

    def done_checks():
        nonlocal changed
        if not st["bought"] and all(_held(con, x["item"], x["system"], g) >= x["qty"] for x in st["buy"]) :
            st["bought"], changed = True, True
        if st["bought"] and not st["started"] and here == home and slots_used > 0:
            st["started"], changed = True, True
    done_checks()

    def buy_lines(items):
        out = []
        for x in items:
            station = _station_of(con, g, x["item"], x["system"])
            out.append(f"      {x['qty']:>6,} x {x['item']:<18} ~{x['cost']:>9,.0f} ISK" + (f"   at {station}" if station else f"   at {x['system']}"))
        return out

    if not st["bought"]:
        missing_near = [x for x in near if _held(con, x["item"], x["system"], g) < x["qty"]]
        missing_far = [x for x in far if _held(con, x["item"], x["system"], g) < x["qty"]]
        if missing_near and here == home:
            txt = [head, "", f"   YOU ARE AT {here}. DO ONLY THIS: buy these here (Market > item > Buy, the cheapest sell order):"] + buy_lines(missing_near)
        elif missing_far and here != st["dest"] and not any(x["system"] == here for x in missing_far):
            try:
                jn = g.route(g.id_of(here), g.id_of(dest), 60, p.avoid_yellow).jumps
            except Exception:                                           # noqa: BLE001
                jn = 3
            txt = [head, "", f"   DO ONLY THIS: fly to {dest} ({jn} jumps). That trip is the goal 'Complete 3 Jumps'. Stay in 0.5+ space."]
            way = _on_the_way(con, g, p, dest)
            txt.append("   ON THE WAY (optional; confirm each buy with `check` first):" if way else "   Nothing worth buying or selling on this route right now.")
            txt += [f"      {x}" for x in way]
        elif missing_far:
            txt = [head, "", f"   YOU ARE AT {here}. DO ONLY THIS: buy these here (Market > item > Buy, the cheapest sell order):"] + buy_lines([x for x in missing_far if x["system"] == here] or missing_far)
            try:
                from .tripplus import cheap_needs_here
                also = cheap_needs_here(con, g, p, home)
            except Exception:                                           # noqa: BLE001
                also = []
            if also:
                txt += ["   ALSO BUY HERE (you need these anyway and they are much cheaper here):"] + [f"      {x}" for x in also]
        else:
            txt = [head, "", "   DO ONLY THIS: load the materials from your hangar into your ship."]
    elif here == dest and dest != home and st["dest"].lower() == "manifest" and not st.get("epic_done"):
        txt = [head, "", f"   YOU ARE AT {here} with the materials. OPTIONAL, DO ONLY THIS: the epic arc agent Cassandra Ahfrim is here (chapter 1 of 'Visions of Greatness').",
               "   Open her window, SCREENSHOT the rewards before you accept, then accept chapter 1. It is a new activity: it adds to the model.",
               "   Not now? Skip it. When done or skipped run:  python -m eve_profit done"]
    elif here != home:
        txt = [head, "", f"   DO ONLY THIS: load the materials into your ship and fly back to {home} (3 jumps: this finishes 'Complete 3 Jumps')."]
    elif not st["started"] and slots_used == 0:
        txt = [head, "", f"   YOU ARE AT {home} with the materials. DO ONLY THIS: Industry > {st['product']} blueprint > {st['runs']} run{'s' if st['runs'] != 1 else ''} > Start",
               f"   (makes {st['units']} items; the job takes ~{st['job_min']:.0f} min)"]
    elif slots_used > 0:
        txt = [head, "", f"   THE BUILD IS RUNNING (~{st['job_min']:.0f} min). DO ONLY THIS: wait for it, then Industry > Jobs > Deliver the finished job.",
               "   (that completes 'Manufacture an Item'; the finished items have no buyer nearby: keep them for cap booster missions)"]
    else:
        txt = [head, "", "   DO ONLY THIS: open Opportunities > AIR Daily Goals in game: both goals should show complete and the reward is paid (445,000 ISK).",
               "   Then stop the timer."]
    if changed or _chain_load(con) is None:
        _chain_save(con, st)
    return "\n".join(txt)
