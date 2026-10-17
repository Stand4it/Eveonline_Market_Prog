"""Hauling candidate for `next`: stock lying here that sells much better at another scanned market. Scored in ISK per hour like every
other activity: (extra ISK vs selling it right here) / (the trip ONE WAY + docking; extra loads add their round trips). There is no planned
return: `next` plans again at every stop, so at the destination the best next step is chosen fresh. Ore may ride in a mining ship's ore hold."""
import math
import os

from .along import keep_rules, keep_split
from .orders import load_books, sell_into_bids
from .sellplan import is_ore, ore_hold_m3

DOCK_MIN = 2.0
MIN_GAIN = 50_000.0
MAX_JUMPS = 25
MAX_TRIPS = 3
TRADE_WALLET_SHARE = 0.30    # side trades may use at most this share of your wallet
TRADE_HAIRCUT = 0.5          # count only half of the projected side-trade profit: prices move and thin orders vanish


def haul_option(con, g, p):
    """Best destination for the stock lying in your current system. -> dict or None."""
    cur = g.id_of(p.current_system)
    reach = g.reach(cur, MAX_JUMPS, p.avoid_yellow)
    _, buys = load_books(con, set(reach))
    vol = {r[0]: r[1] for r in con.execute("SELECT type_id,volume FROM types")}
    name = {r[0]: r[1] for r in con.execute("SELECT type_id,name FROM types")}
    ore_cap, cargo = ore_hold_m3(con, p), max(p.cargo_m3, 1.0)
    keep = keep_rules(con)                                   # gear you plan to use (probes, miners...) is never hauled off to sell
    per_dest = {}
    for inv in con.execute("SELECT type_id,quantity FROM inventory WHERE system_id=?", (cur,)).fetchall():
        tid, qty = inv["type_id"], inv["quantity"]
        _k, qty = keep_split(keep, name.get(tid, ""), qty)
        if qty <= 0:
            continue
        _, local = sell_into_bids(buys.get(tid, {}).get(cur, []), qty, p.sales_tax)
        best = None
        for b, bids in buys.get(tid, {}).items():
            if b == cur:
                continue
            sold, net = sell_into_bids(bids, qty, p.sales_tax)
            if sold and (best is None or net > best[1]):
                best = (b, net, sold)
        if not best or best[1] - local < 10_000:
            continue
        b, net, sold = best
        m3 = sold * (vol.get(tid, 0) or 0.0001)
        d = per_dest.setdefault(b, {"gain": 0.0, "net": 0.0, "ore_m3": 0.0, "other_m3": 0.0, "items": []})
        d["gain"] += net - local
        d["net"] += net
        d["ore_m3" if is_ore(name.get(tid, "")) and ore_cap else "other_m3"] += m3
        d["items"].append((name.get(tid, tid), sold, net, local))
    out = None
    for b, d in per_dest.items():
        trips = max(math.ceil(d["ore_m3"] / ore_cap) if d["ore_m3"] else 0, math.ceil(d["other_m3"] / cargo) if d["other_m3"] else 0, 1)
        if trips > MAX_TRIPS:
            continue
        j = reach[b].jumps
        one_way = j * p.jump_seconds / 60.0 + DOCK_MIN                      # you re-plan AT the destination: no return trip is counted for the first load
        minutes = one_way + (trips - 1) * (2 * j * p.jump_seconds / 60.0 + 2 * DOCK_MIN)       # only extra loads need the round trip back
        gain = d["gain"]
        if gain < MIN_GAIN or minutes <= 0:
            continue
        cand = {"dest": g.name[b], "jumps": j, "trips": trips, "minutes": minutes, "gain": gain, "rate_hr": gain * 60.0 / minutes,
                "items": sorted(d["items"], key=lambda x: -x[2]), "net": d["net"], "ore": bool(d["ore_m3"]), "ore_cap": ore_cap,
                "other_m3": d["other_m3"], "gain_stock": gain, "minutes_stock": minutes, "extra_lines": []}
        if out is None or cand["rate_hr"] > out["rate_hr"]:
            out = cand
    if out:
        enrich_route(con, g, p, out)
    return out


def enrich_route(con, g, p, h):
    """Everything on the way: trades along the route there and back with the spare hold (ore does not use the cargo hold), the best other
    activity once you are AT the destination, agents there, and the repeat trips. Updates the ISK/hr of the whole plan."""
    import dataclasses
    from .nextstep import trade_extras
    extra_isk, extra_min, lines = 0.0, 0.0, []
    try:
        hold = min(h["other_m3"], p.cargo_m3) if h["other_m3"] else 0.0
        capped = dataclasses.replace(p, wallet_isk=p.wallet_isk * TRADE_WALLET_SHARE)           # never put the whole wallet into side trades
        isk, mins, tl = trade_extras(con, g, capped, {"to_system": h["dest"], "m3": hold, "one_way": True})
        isk *= TRADE_HAIRCUT                                                                    # prices move before you get there
        if isk > 0:
            lines += [f"ON THE WAY (spare hold, one way; at most {TRADE_WALLET_SHARE:.0%} of your wallet; counted at {TRADE_HAIRCUT:.0%} because prices move; "
                      "CONFIRM each buy with `check`/the market window first, a huge margin on one unit is often a trap):"] + ["      " + x for x in tl]
            for k in range(h["trips"]):
                extra_isk += isk * (1.0 if k == 0 else 0.5)             # repeat trips: market depth is partly used up
                extra_min += mins
    except Exception:                                                   # noqa: BLE001
        pass
    try:
        from .planner import plan
        there = dataclasses.replace(p, current_system=h["dest"])
        opps = plan(con, there, 3, False)
        if opps:
            o = opps[0]
            lines.append(f"AT {h['dest']} after selling: next best activity there is {o.kind} '{o.description[:70]}' ~{o.isk_per_hour:,.0f} ISK/hr "
                         "(`next` re-plans from wherever you are)")
    except Exception:                                                   # noqa: BLE001
        pass
    try:
        did = g.id_of(h["dest"])
        ag = con.execute("SELECT level,COUNT(*) FROM agents WHERE system_id=? GROUP BY level ORDER BY level", (did,)).fetchall()
        if ag:
            lines.append(f"AGENTS at {h['dest']}: " + ", ".join(f"{n} level-{lv}" for lv, n in ag)
                         + " - open their windows: a mission you can do there beats flying back empty")
    except Exception:                                                   # noqa: BLE001
        pass
    if h["trips"] > 1:
        lines.append(f"{h['trips']} trips needed: the first load goes one way; the return for the next batch is decided when you get there.")
    h["extra_lines"] = lines
    if extra_isk:
        total_isk, total_min = h["gain_stock"] + extra_isk, h["minutes_stock"] + extra_min
        h["gain"], h["rate_hr"], h["minutes"] = total_isk, total_isk * 60.0 / total_min, total_min
        h["extra_isk"] = extra_isk
    return h


def _hop(g, p, dest):
    """(next system name, jumps left, total jumps) on the safe route from where you are to dest; (None, 0, 0) if none."""
    try:
        r = g.route(g.id_of(p.current_system), g.id_of(dest), 60, p.avoid_yellow)
        if r and len(r.path) > 1:
            return g.name[r.path[1]], r.jumps, r.jumps
    except Exception:                                                   # noqa: BLE001
        pass
    return None, 0, 0


def agents_on_route(g, p, dest):
    """Known agents (agents_nearby.json, from the Agency window) in the systems you pass, destination included. -> list of lines."""
    import json, os
    f = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agents_nearby.json")
    try:
        d = json.load(open(f, encoding="utf-8"))
        r = g.route(g.id_of(p.current_system), g.id_of(dest), 60, p.avoid_yellow)
        names = {g.name[x] for x in r.path[1:]}
    except Exception:                                                   # noqa: BLE001
        return []
    return _agents_in(d, names)


def agents_near(g, p, system, max_jumps=2):
    """Every known agent (agents_nearby.json + agent_offers.json), distance recomputed from where you stand now. -> lines, nearest first:
    0 jumps = here (dock at the station: that is a stop); 1-2 jumps = a possible next stop."""
    import json, os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    seen, found = set(), []

    def add(name, sysname, kind):
        if not name or not sysname or (name, sysname) in seen:
            return
        seen.add((name, sysname))
        try:
            j = 0 if sysname == system else g.route(g.id_of(system), g.id_of(sysname), 60, p.avoid_yellow).jumps
        except Exception:                                               # noqa: BLE001
            return
        if j <= max_jumps:
            found.append((j, name, sysname, kind))
    try:
        d = json.load(open(os.path.join(root, "agents_nearby.json"), encoding="utf-8"))
        for kind in ("security", "mining", "distribution_nearest", "locator_nearest", "rd_nearest"):
            for a in d.get(kind, []):
                add(a.get("agent"), a.get("system"), kind.split("_")[0])
    except Exception:                                                   # noqa: BLE001
        pass
    try:
        for x in json.load(open(os.path.join(root, "agent_offers.json"), encoding="utf-8")).get("offers", []):
            nm = x.get("agent", "").split(" (")[0]
            if not nm.startswith("BOTH"):
                add(nm, x.get("agent_system"), "career/mission")
    except Exception:                                                   # noqa: BLE001
        pass
    out = []
    for j, name, sysname, kind in sorted(found):
        if j == 0:
            out.append(f"HERE in {sysname}: {name} ({kind}): dock at the station and open the Agents tab")
        else:
            out.append(f"{j} jump{'s' if j != 1 else ''} away in {sysname}: {name} ({kind})" + (" - could be your next stop" if j == 1 else ""))
    return out


def agents_here(system, g=None, p=None):
    """Known agents near the system you are in. With the map: distances from here; without: only agents in this very system."""
    if g is not None and p is not None:
        return agents_near(g, p, system)
    return []


def _agents_in(d, names):
    out = []
    for kind in ("security", "mining", "distribution_nearest", "locator_nearest", "rd_nearest"):
        for a in d.get(kind, []):
            if a.get("system") in names and a.get("agent"):
                out.append(f"AGENT at {a['system']}: {a['agent']} ({kind.split('_')[0]}, level {a.get('level', 1)}): look at the offer when you stop there; a new mission may have appeared")
    return out


HAUL_GEAR = (("expanded cargohold", "low slot: more cargo space"), ("inertial stabilizers", "low slot: faster align, quicker warps"),
             ("nanofiber", "low slot: faster align"), ("afterburner", "mid slot: faster in a gate-to-gate hop"),
             ("overdrive", "low slot: faster ship"))


FLEX_GEAR = (("miner", "mining"), ("strip miner", "mining"), ("probe launcher", "exploration / data and relic sites"), ("core scanner probe", "exploration / data and relic sites"),
             ("analyzer", "data and relic sites"), ("gatling", "combat missions (needs a weapon fitted)"), ("autocannon", "combat missions"), ("rail", "combat missions"),
             ("armor repairer", "repair missions / tank"), ("remote armor repair", "Arabeton's repair mission"), ("salvager", "salvage"),
             ("warp disruptor", "Arabeton's warp-disrupt mission"), ("antimatter", "ammo for the gatling"))


def ship_lines(con, g, p, h):
    """Which ship makes the trip and which modules you OWN (in the hangar here) are worth fitting for it. -> list of lines."""
    L = []
    need = h.get("other_m3", 0.0) + (0.0 if h.get("ore") else 0.0)
    here = g.id_of(p.current_system)
    fly = f"your {p.ship_name} (cargo {p.cargo_m3:,.0f} m3)"
    trips = max(1, -(-int(need) // int(max(p.cargo_m3, 1)))) if need else 1
    L.append(f"SHIP: {fly}, the stock is {need:,.1f} m3 -> " + ("fits in 1 trip" if trips == 1 else f"{trips} trips"))
    if trips > 1 and con is not None:
        try:
            from .fleet import parked_ships
            for sh in sorted((x for x in parked_ships(con) if x["system_id"] == here and x["capacity"] > p.cargo_m3), key=lambda x: x["capacity"]):
                t2 = max(1, -(-int(need) // int(sh["capacity"])))
                L.append(f"      better: swap to your parked {sh['name']} (cargo {sh['capacity']:,.0f} m3) -> {t2} trip{'s' if t2 != 1 else ''}")
                break
        except Exception:                                               # noqa: BLE001
            pass
    if con is not None:
        fitted = {r[0].lower() for r in con.execute("SELECT t.name FROM fitted f JOIN types t ON t.type_id=f.type_id")}
        rows = con.execute("SELECT t.name,i.quantity FROM inventory i JOIN types t ON t.type_id=i.type_id WHERE i.system_id=?", (here,)).fetchall()
        fit = []
        for key, why in HAUL_GEAR:
            for r in rows:
                n = str(r["name"])
                if key in n.lower() and n.lower() not in fitted:
                    fit.append(f"      FIT {r['quantity']} x {n} ({why}) - you own it, it is in your hangar here")
        L += fit or ["      FIT: nothing in your hangar here helps this trip; fly as you are"]
        seen, flex = set(), []
        for r in rows:
            n = str(r["name"])
            for key, why in FLEX_GEAR:
                if key in n.lower() and n.lower() not in fitted and n not in seen:
                    seen.add(n)
                    flex.append(f"      KEEP FLEXIBLE: {r['quantity']} x {n} ({why}): do NOT sell it; carry it on this trip so the next stop can switch activity")
        L += flex[:6]
        L.append("      (check the fitting window: I cannot see free slots, so fit only what has a free slot)")
    return L


def hop_only(text, here=None):
    """KISS: the step is the next jump and what to load; the end point, the money and the 'after selling' view wait for `next --plan`."""
    import re
    out = []
    lines = text.split("\n")
    for ln in lines:
        if here and re.match(r"^\s{6}(buy|sell|need anyway)", ln):             # a stop elsewhere is not part of THIS step: it comes up when you are there
            m = re.search(r"(?:buy .*? at|sell .*? at|need anyway: .*? at) (.+?)(?: \(| on the route|$)", ln)
            if m and m.group(1).strip().lower() != here.lower():
                continue
        gm = re.match(r"^\s+(going|coming back):\s*(.*)$", ln)
        if gm and here:                                                   # trades of the route: only a buy/sell in THIS system is part of this step; the rest (and the money total) wait for `next --plan` / that system
            m = re.search(r"(?:buy|sell) .*? at (.+?)(?: \(|$)", gm.group(2))
            if not m or m.group(1).strip().lower() != here.lower():
                continue
        rm = re.match(r"^\s*agent on the route: .*\(\w[\w ]*, ([^)]+)\):", ln)
        if rm and here and rm.group(1).strip().lower() != str(here).lower():          # an agent in a system you have not reached yet comes up when you are there
            continue
        am = re.match(r"^\s*AGENTS? at (.+?):", ln)
        if am and (not here or am.group(1).strip().lower() != str(here).lower()):          # agents in a system you are NOT in belong to `next --plan`, not to this step
            continue
        if ln.startswith("STEP: FLY to"):
            ln = re.sub(r", hauling your stock to .*$", "", ln)
            ln = re.sub(r" - jump \d+ of \d+", "", ln)
        elif re.search(r"trip\(s\), about|^\s+AT .* after selling|^\s+includes about", ln):
            continue
        elif "DO ONLY THIS" in ln:
            ln = re.sub(r"\s*\(it plans again.*\)\.?$", "", ln)
            ln = ln.replace("and stop there. Then run", "and stop there. Then run")
        else:
            m = re.match(r"^(\s+[\d,]+ x .+?)(\s{2,}.*there vs.*|\s+~\s.*)$", ln)
            if m:
                ln = m.group(1)
        out.append(ln)
    res = []
    for i, ln in enumerate(out):                                        # drop section headers whose lines were all removed
        if re.match(r"^\s+(ON THE WAY|ALSO ON THE ROUTE)", ln) and not ln.strip().startswith("ON THE WAY: nothing"):
            nxt = out[i + 1] if i + 1 < len(out) else ""
            if not re.match(r"^\s{6}\S", nxt):
                if ln.strip().startswith("ON THE WAY"):
                    res.append("   ON THE WAY: nothing to buy or sell on this hop.")
                continue
        res.append(ln)
    return "\n".join(res)


def haul_step(h, g=None, p=None, con=None):
    """The haul as ONE jump at a time: the first jump is the step; at every stop `next` plans again."""
    hop = _hop(g, p, h["dest"]) if (g is not None and p is not None) else (None, 0, 0)
    L = [f"STEP: FLY to {hop[0]} - jump 1 of {hop[2]}, hauling your stock to {h['dest']}" if hop[0]
         else f"STEP: HAUL your stock to {h['dest']} ({h['jumps']} jumps, one way: `next` plans again at every stop)"]
    for n, q, net, local in h["items"][:6]:
        L.append(f"   {q:>9,} x {n:<32} {net:>12,.0f} there vs {local:>10,.0f} here")
    L.append(f"   {h['trips']} trip(s), about {h['minutes']:.0f} min, +{h['gain']:,.0f} ISK more than selling here = {h['rate_hr']:,.0f} ISK/hr"
             + ("   (ore rides in your mining ship's ore hold)" if h["ore"] else ""))
    if hop[0]:
        L.append(f"   DO ONLY THIS: load the stock into your ship and fly to {hop[0]} and stop there. Then run  python -m eve_profit next  (it plans again from there: {h['jumps']} jumps left to {h['dest']}, no planned trip back).")
    if g is not None and p is not None:
        try:
            L += ["   " + x for x in agents_on_route(g, p, h["dest"])]
            L += ["   " + x for x in ship_lines(con, g, p, h)]
        except Exception:                                               # noqa: BLE001
            pass
    if h.get("extra_isk"):
        L.append(f"   includes about +{h['extra_isk']:,.0f} ISK of trades along the route")
    L += ["   " + x for x in h.get("extra_lines", [])]
    if not any(x.startswith("ON THE WAY") for x in h.get("extra_lines", [])):
        L.append("   ON THE WAY: nothing worth buying or selling on this route right now.")
    return "\n".join(L)


def agents_in_system(g, p):
    """Known agents in the system you stand in: lines for the current step ('accept a mission in passing')."""
    import json
    f = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agents_nearby.json")
    try:
        return _agents_in(json.load(open(f, encoding="utf-8")), {p.current_system})
    except Exception:                                                   # noqa: BLE001
        return []
