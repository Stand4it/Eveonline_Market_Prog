"""SHOPPING AS PART OF THE PLAN: the ships, modules and ammo the plan needs are bought where they are CHEAPEST (buy vs build, detours counted at the value of
your time), at the moment your route is in that place, and every later plan then uses what you own. A wish is one of: a missing piece of the combat kit (hull, guns,
ammo, tank: combatprep) or an extra you list in ship_fits.json under "wishlist" ([{"item": "Expanded Cargohold I", "qty": 1, "why": "more m3 for hauls"}]: an upgrade to a ship you own).
`candidates` offers a purchase as a step only when THIS place is the cheapest source; `lines` lists every wish with its cheapest source for `next --plan`."""
import json
import os

_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ship_fits.json")
MAX_SHARE = 0.10            # never spend more than a tenth of the wallet on one opportunistic purchase
RATE_EDGE = 1.2             # a purchase at the best place ranks just above the best step (so the 15% no-flip rule lets it through)


def _extras():
    try:
        with open(_FILE, encoding="utf-8") as f:
            return json.load(f).get("wishlist", [])
    except (OSError, ValueError):
        return []


def wishes(con, p, g=None):
    """-> [{item, qty, why}] still missing, in the order they are needed."""
    from . import acquire, combatprep
    out = []
    if g is not None:
        try:
            hu = hull_unlock(con, g, p)
            if hu:
                out.append(hu)
        except Exception:                                               # noqa: BLE001
            pass
    try:
        k = combatprep.kit()
        s = combatprep.state(con, p)
        if not any(h.lower() in (s["hull"] or "").lower() for h in k["hulls"]) and not any(any(h.lower() in n.lower() for h in k["hulls"]) for n, _sid in s["ships"]):
            out.append({"item": k["hulls"][0], "qty": 1, "why": "combat hull (you own none)"})
        have_t = sum(q for n, q in s["fitted"] if any(w in n.lower() for w in k["turret_words"]))
        have_t += sum(sum(q for _sid, q in rows) for n, rows in s["stock"].items() if any(w in n.lower() for w in k["turret_words"]) and "civilian" not in n.lower())
        if have_t < k["turrets"]:
            out.append({"item": k["turret_buy"], "qty": k["turrets"] - have_t, "why": "guns for the combat fit", "needs_combat_hull": True})
        if acquire.held(con, k["ammo"]) < k["ammo_qty"]:
            out.append({"item": k["ammo"], "qty": k["ammo_qty"] - acquire.held(con, k["ammo"]), "why": "ammo for the guns", "needs_combat_hull": True})
        has_tank = any(any(w in n.lower() for w in k["tank_words"]) for n, _q in s["fitted"]) or any(
            any(w in n.lower() for w in k["tank_words"]) for n in s["stock"]) or acquire.held(con, k["tank_buy"]) >= 1
        if not has_tank:
            out.append({"item": k["tank_buy"], "qty": 1, "why": "armor repairer (tank)", "needs_combat_hull": True})
    except Exception:                                                   # noqa: BLE001
        pass
    try:                                                                # the TOOLS the other careers need (scanning, salvaging, mining): any hull with the slots carries them
        from . import tools as _tl
        if (getattr(p, "ship_name", "") or ""):
            fitted, held = _tl.fitted_now(con), _tl.held_anywhere(con)
            car = _tl.carrier(con, p)
            fit = dict(car[2]) if car else {}
            for t in _tl.PRIORITY:
                if car and t not in fit:
                    continue                                            # the best hull you own has no slots left for this tool
                for item, qty in _tl.TOOLS[t]["buy"]:
                    qty = fit.get(t, qty) if t == "mining" else qty
                    first = item == _tl.TOOLS[t]["buy"][0][0]
                    have = (fitted[t] + held[t]) if first else acquire.held(con, item)
                    if have < qty:
                        why = f"{_tl.TOOLS[t]['label']} for {t}" + (f" (fits your {car[0]}: {car[1].get('high', '?')} high slots)" if car else "")
                        out.append({"item": item, "qty": qty - have, "why": why})
    except Exception:                                                   # noqa: BLE001
        pass
    if g is not None:
        try:                                                            # a hull that carries more tools at once than your best one, at the lowest price per extra tool
            from . import ships as _ships
            up = _ships.upgrade(con, g, p)
            if up and up["item"].lower() not in {w["item"].lower() for w in out}:      # the combat hull may already be the wish
                out.append(up)
        except Exception:                                               # noqa: BLE001
            pass
    for w in _extras():
        try:
            need = int(w.get("qty", 1)) - acquire.held(con, w["item"])
            if need > 0:
                out.append({"item": w["item"], "qty": need, "why": w.get("why", "upgrade")})
        except Exception:                                               # noqa: BLE001
            continue
    return out


GOAL_ISK = 222_500.0                                  # an AIR daily goal pays about 445,000 ISK for two, so about this per goal
BLOCKED_MIN = {"Scan 5 Signatures": 35.0, "Mine 2000 units of Ore": 15.0}


def _launcher_hulls(con, g, p):
    """-> (owned hulls with a launcher hardpoint [(name, where)], cheapest flyable hull on the market with one (name, price, jumps, system) or None)."""
    from . import shipslots, ships, skills
    own = [(n, g.name.get(sid, "with you") if sid else "with you") for n, sid, sl in shipslots.owned_hulls(con, p) if sl and sl.get("launcher", 0) >= 1 and not n.lower().startswith("capsule")]
    best = None
    try:
        have, prices = skills.have(con), ships._prices(con, g, p)
        for tid, d in ships.catalog(con).items():
            if d["slots"].get("launcher", 0) < 1 or not ships._flyable(con, tid, have)[0] or d["name"] not in prices:
                continue
            pr = prices[d["name"]]
            if best is None or pr[0] < best[1]:
                best = (d["name"], pr[0], pr[1], pr[2])
    except Exception:                                                   # noqa: BLE001
        pass
    return own, best


def blocked_goals(con, g, p):
    """AIR daily goals that cannot be done NOW for lack of ship or tools, by ISK per MINUTE: [{goal, per_min, minutes, lines}] (lines = how to get able to do it)."""
    from . import dailygoals as dg
    today = dg.today_goals()
    out = []
    for o in (dg.scan_option(con), dg.mine_option(con)):
        if o["ok"] or (today and o["goal"] not in today):
            continue
        minutes = BLOCKED_MIN.get(o["goal"], 30.0)
        lines = []
        if o["goal"] == "Scan 5 Signatures":
            own, cheap = _launcher_hulls(con, g, p) if g is not None else ([], None)
            if own:
                lines.append("hull: " + ", ".join(f"your {n} ({w})" for n, w in own[:2]) + " has a launcher hardpoint: fly it")
            elif cheap:
                lines.append(f"hull: no ship you own has a launcher hardpoint; the cheapest you can fly that has one: {cheap[0]} ~{cheap[1]:,.0f} ISK at {cheap[3]} ({cheap[2]} jumps)")
            else:
                lines.append("hull: none you own is known to have a launcher hardpoint (run  python -m eve_profit ships --refresh  to read ship slots)")
            for item, qty in (("Core Probe Launcher I", 1), ("Core Scanner Probe I", 8)):
                w = _way(con, g, p, {"item": item, "qty": qty}) if g is not None else None
                if w and w.get("buy"):
                    lines.append(f"{qty} x {item}: ~{w['buy']['price'] * w['qty']:,.0f} ISK at {w['buy']['system']} ({w['buy']['jumps']} jumps)")
        else:
            lines.append(o.get("why_not", "needs gear"))
        out.append({"goal": o["goal"], "per_min": GOAL_ISK / minutes, "minutes": minutes, "lines": lines, "why": o.get("why_not", "")})
    out.sort(key=lambda d: -d["per_min"])
    return out


def _offers_waiting():
    """[(m3, reward ISK incl. bonus)] of the open courier (Distribution) offers you could do with a ship that has a hold."""
    import os
    try:
        offers = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent_offers.json"), encoding="utf-8")).get("offers", [])
    except (OSError, ValueError):
        return []
    return [(float(o.get("m3", 0.0)), float(o.get("isk", 0)) + float(o.get("bonus", 0))) for o in offers
            if o.get("available") and o.get("career") == "Distribution" and o.get("m3") is not None]


def hull_unlock(con, g, p):
    """No ship with a hold at hand (a capsule, nothing parked here) but courier offers wait: the cheapest hull you can fly that carries the most of them.
    -> {item, qty, why, unlock: reward ISK, rate: ISK/hr} or None. Buying it is PROGRESS: it turns waiting offers into ISK and every later plan uses it."""
    if _ship_here(con, g, p):
        return None
    waiting = _offers_waiting()
    if not waiting:
        return None
    try:
        from . import ships, skills
        cat, prices, have = ships.catalog(con), ships._prices(con, g, p), skills.have(con)
        cap = {r[0]: float(r[1] or 0.0) for r in con.execute("SELECT type_id,capacity FROM types WHERE category_id=6")}
    except Exception:                                                   # noqa: BLE001
        return None
    wallet = float(getattr(p, "wallet_isk", 0.0) or 0.0)
    best = None
    for tid, d in cat.items():
        pr = prices.get(d["name"])
        room = cap.get(int(tid), 0.0)
        if not pr or room <= 0 or pr[0] > wallet * MAX_SHARE or not ships._flyable(con, tid, have)[0]:
            continue
        got = [r for m, r in waiting if m <= room]
        if not got:
            continue
        gain = sum(got) - pr[0]
        if best is None or gain > best[0]:
            best = (gain, d["name"], len(got), sum(got), pr[0], room)
    if not best:
        return None
    _g, name, n, reward, price, room = best
    rate = reward * 60.0 / (n * 20.0 + 30.0)                            # about 20 minutes per offer (travel, dock, hand-in) plus half an hour to get set
    return {"item": name, "qty": 1, "unlock": reward, "rate": rate,
            "why": f"unlock: a ship with {room:,.0f} m3 of hold turns {n} waiting courier offers into about {reward:,.0f} ISK (the hull costs ~{price:,.0f})"}


def _owns_blueprint(con, item):
    """True when you own the blueprint of `item` (a build is only an option then; without it the only way is to buy)."""
    try:
        return con.execute("SELECT 1 FROM my_blueprints b JOIN types t ON t.type_id=b.blueprint_id WHERE t.name=? COLLATE NOCASE LIMIT 1", (item + " Blueprint",)).fetchone() is not None
    except Exception:                                                   # noqa: BLE001
        return False


def _way(con, g, p, w, live=False):
    from . import acquire
    try:
        return acquire.best_way(con, g, p, w["item"], w["qty"], None, can_build=_owns_blueprint(con, w["item"]), live=live)
    except Exception:                                                   # noqa: BLE001
        return None


def _ship_here(con, g, p):
    """True when you fly a ship (not a capsule) or one of your ships is parked in THIS system: what you buy can be fitted right away."""
    from . import combatprep
    try:
        if (p.ship_name or "") and not p.ship_name.lower().startswith("capsule"):
            return True
        here = g.id_of(p.current_system)
        return any(sid == here for _n, sid in combatprep.state(con, p)["ships"])
    except Exception:                                                   # noqa: BLE001
        return False


def has_combat_hull(con, p):
    """True when you fly or own a hull of the combat kit (guns, ammo and a tank bought before it would only sit in a hangar)."""
    from . import combatprep
    try:
        k, st = combatprep.kit(), combatprep.state(con, p)
        hulls = [h.lower() for h in k["hulls"]]
        return any(h in (st["hull"] or "").lower() for h in hulls) or any(any(h in n.lower() for h in hulls) for n, _sid in st["ships"])
    except Exception:                                                   # noqa: BLE001
        return False


def candidates(con, g, p, best_known, hop_to):
    """-> [(rate, label, step text, note)]: a purchase step when THIS system is the cheapest way (buy beats build, detours counted) to get a wished item."""
    from . import acquire
    out = []
    wallet = float(getattr(p, "wallet_isk", 0.0) or 0.0)
    hull_ok = has_combat_hull(con, p)
    ship_here = _ship_here(con, g, p)
    for w in wishes(con, p, g):
        if w.get("needs_combat_hull") and not hull_ok:
            continue                                                    # no combat hull yet: the hull comes first, these would only sit in a hangar
        if not w["why"].startswith(("combat hull", "upgrade", "unlock")) and not ship_here:
            continue                                                    # a module or ammo bought where no ship of yours is would just sit in the hangar: buy it when you are with the ship
        way = _way(con, g, p, w)
        if w.get("unlock") and way and way["mode"] == "buy" and way.get("buy") and way["buy"]["system"] != p.current_system:
            txt = acquire.first_action(con, g, p, way, hop_to)           # the hop toward the cheapest hull: progress ranks above the plain best step
            if txt.startswith("STEP:"):
                return [(max(best_known * 1.25, w["rate"]), f"shopping: {w['item']}", txt, w["why"])]
            continue
        if not way or way["mode"] != "buy" or not way.get("buy") or way["buy"]["system"] != p.current_system:
            continue
        if way["buy"]["price"] * way["qty"] > wallet * MAX_SHARE:
            continue
        way = _way(con, g, p, w, live=True) or way                      # today's prices for the step you are about to act on
        if not way.get("buy") or way["mode"] != "buy" or way["buy"]["system"] != p.current_system:
            continue
        txt = acquire.first_action(con, g, p, way, hop_to)
        if not txt.startswith("STEP:"):
            continue
        note = f"{w['why']}: this is the cheapest place to buy it (cheaper than building it); the plan then uses what you own"
        out.append((max(best_known, 1.0) * RATE_EDGE, f"shopping: {w['item']}", txt, note))
        break                                                           # one purchase at a time
    return out


def lines(con, g, p):
    """-> text for the long view: every wish with its cheapest source."""
    ws = wishes(con, p, g)
    if not ws:
        return ""
    L = ["SHOPPING (bought where cheapest, when your route passes: every later step then uses what you own):"]
    try:
        from . import tools as _tl
        car = _tl.carrier(con, p)
        if car:
            sl = car[1]
            L.append(f"   BEST CARRIER you own: {car[0]} ({sl.get('high', 0)} high slots, {sl.get('turret', 0)} turret and {sl.get('launcher', 0)} launcher hardpoints): "
                     "carries at the same time " + (", ".join(f"{n} x {t}" for t, n in car[2]) or "nothing yet") + " (a bigger hull carries more)")
        else:
            L.append("   Hull slots are not known yet: run  python -m eve_profit sync  (it reads them for the ship you fly and every ship you own)")
    except Exception:                                                   # noqa: BLE001
        pass
    try:
        bl = blocked_goals(con, g, p)
    except Exception:                                                   # noqa: BLE001
        bl = []
    if bl:
        L.append("   BLOCKED DAILY GOALS (by ISK per minute; each joins the plan as soon as you can do it; what is missing is bought when your route passes):")
        for b in bl:
            L.append(f"      {b['goal']}: ~{b['per_min']:,.0f} ISK/min ({b['per_min'] * 60:,.0f} ISK/hr) once able; {b['why']}")
            L += [f"         needs {x}" for x in b["lines"]]
    for w in ws:
        way = _way(con, g, p, w)
        if not way or not way.get("buy"):
            L.append(f"   {w['qty']} x {w['item']} ({w['why']}): no price scanned yet (run  python -m eve_profit scan)")
            continue
        b = way["buy"]
        cheaper = ""
        if way.get("build") and way["mode"] == "buy":
            cheaper = f"; building would cost about {way['build']['cost']:,.0f}"
        elif way["mode"] == "build":
            cheaper = "; BUILDING is cheaper than buying"
        where = "HERE" if b["system"] == p.current_system else f"{b['system']} ({b['jumps']} jumps)"
        L.append(f"   {w['qty']} x {w['item']} ({w['why']}): ~{b['price'] * way['qty']:,.0f} ISK at " + (f"{b['station']}, " if b['station'] and b['station'] != b['system'] else "") + f"{where}{cheaper}")
    return "\n".join(L)
