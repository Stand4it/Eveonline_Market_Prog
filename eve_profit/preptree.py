"""PREP TREE (owner 2026-10-28): every blocked goal (combat offers and combat activities, offers and activities that need a tool) joins the long plan by
ISK per minute TOGETHER with what it costs to get able to do it. Each missing item is sourced the cheapest way, recursively:
   HELD   you own it: free;
   BUY    the cheapest safe ask in reach (price + the trip at your ISK/min);
   BUILD  its blueprint (owned = free, else bought) + the materials (each again BUY or MINE) + the job fee; a batch may be built and the rest SOLD
          at the best buy order in reach (make one for yourself, sell the others), whichever batch size costs least net;
   MINE   a mineral: mine the ore in reprocess.json, refine it, keep what the build needs and sell the other minerals.
Costs are ISK-equivalent: cash + your minutes x the best ISK/min on the list (that is what the time would make elsewhere). Hauling trades on the
first trip are subtracted (plan_along's carry). A goal that is not modeled yet (no timed runs) is valued at the best ISK/min on the list.
A GROUP = goals that need the same prep (all combat needs one combat fit). Its chain ISK/min = (what the goals pay - prep cash + haul gain) /
(goal minutes + prep minutes). When a chain beats the best step now, its FIRST step (the first leaf of the tree) joins `next`."""
import json
import math
import os

from .health import record as _hrec

PER_JUMP_MIN = 3.0
BUY_MIN = 2.0                 # dock, find it, buy
BUILD_MIN = 4.0               # start the job once the materials are in the hangar
REFINE_MIN = 3.0
SELL_MIN = 2.0
DEFAULT_YIELD_M3_S = 1.33     # two Miner I (40 m3 / 60 s each) when the profile has no measured yield (a guess until timed)
ACTIVITY_MIN = 600.0          # an open-ended activity counts 10 hours of work: the hull, gear and skills are reused, so their cost is spread over them
BATCHES = (1, 2, 5, 10)
MAX_DEPTH = 3
PLAY_H = 24.0                 # a chain that waits for skill training ranks at chain x 24 / (24 + training hours)
TIE = 0.95                   # a chain within 5% of the best step counts as a tie (its few prep minutes); a tie whose first step is HERE wins (owner rule)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _q(con, sql, args=()):
    try:
        return con.execute(sql, args).fetchall()
    except Exception:                                                   # noqa: BLE001
        return []


def _type(con, name):
    r = _q(con, "SELECT type_id, name, volume FROM types WHERE name=? COLLATE NOCASE", (name,))
    return r[0] if r else None


class Ctx:
    """What one tree build shares: your ISK per MINUTE (time value), the reach map and caches."""

    def __init__(self, con, g, p, rate_min):
        self.con, self.g, self.p, self.rate_min = con, g, p, max(float(rate_min or 0.0), 0.0)
        self.cur = g.id_of(p.current_system)
        self.reach = g.reach(self.cur, 14, p.avoid_yellow)
        self.tax = float(getattr(p, "sales_tax", None) or 0.075)
        self.fee_rate = float(getattr(p, "job_fee_rate", None) or 0.05)
        self.cache = {}

    def isk(self, minutes):
        return minutes * self.rate_min


def _held(ctx, name):
    from .acquire import held
    return held(ctx.con, name)


def best_bid(ctx, name, qty):
    """Where selling `qty` x name pays most after tax and the trip: (net ISK, system, jumps) or (0, None, 0)."""
    t = _type(ctx.con, name)
    if not t or qty <= 0:
        return 0.0, None, 0
    best = (0.0, None, 0)
    for sid, price in _q(ctx.con, "SELECT system_id, MAX(price) FROM orders WHERE type_id=? AND is_buy=1 GROUP BY system_id", (t[0],)):
        if sid not in ctx.reach or not price:
            continue
        j = ctx.reach[sid].jumps
        net = float(price) * qty * (1 - ctx.tax) - ctx.isk(2 * j * PER_JUMP_MIN + SELL_MIN)
        if net > best[0]:
            best = (net, ctx.g.name[sid], j)
    return best


def _buy(ctx, name, qty):
    from .acquire import sources
    src = sources(ctx.con, ctx.g, ctx.p, name, qty, limit=4)
    if not src:
        return None
    s = src[0]
    minutes = 2 * s["jumps"] * PER_JUMP_MIN + BUY_MIN
    return {"how": "buy", "item": name, "qty": qty, "cash": s["price"] * qty, "minutes": minutes, "where": s["system"], "jumps": s["jumps"], "src": s,
            "cost": s["price"] * qty + ctx.isk(minutes), "children": [], "text": f"BUY {qty:,} x {name} at {s['station'] or s['system']} ({s['jumps']} jumps) ~{s['price'] * qty:,.0f} ISK"}


def _mine(ctx, name, qty, depth):
    """A mineral from mining + refining the ore in reprocess.json that yields most of it; the other minerals are sold where they pay most."""
    try:
        from .reprocess import load
        ores = load().get("ores", {})
    except Exception:                                                   # noqa: BLE001
        return None
    cands = [(o, d["per_unit"][k]) for o, d in ores.items() for k in d.get("per_unit", {}) if k.lower() == name.lower() and d["per_unit"][k] > 0]
    if not cands:
        return None
    ore, per = max(cands, key=lambda c: c[1])
    t = _type(ctx.con, ore) or _type(ctx.con, ore.split(" 0-")[0])
    vol = float(t[2]) if t and t[2] else 0.15
    units = math.ceil(qty / per)
    y = float(getattr(ctx.p, "mining_yield_m3_s", 0.0) or 0.0) or DEFAULT_YIELD_M3_S
    minutes = units * vol / y / 60.0 + REFINE_MIN
    fee = float(load().get("fee_per_unit", 0.0)) * units
    surplus, lines = 0.0, []
    for m, pu in ores[ore]["per_unit"].items():
        left = int(units * pu) - (qty if m.lower() == name.lower() else 0)
        if left > 0:
            net, where, _j = best_bid(ctx, m, left)
            if net > 0:
                surplus += net
                lines.append(f"sell the other {left:,} x {m} at {where} (~{net:,.0f})")
    yield_note = "" if getattr(ctx.p, "mining_yield_m3_s", 0) else f" (yield guessed at {DEFAULT_YIELD_M3_S} m3/s until a timed mining run)"
    kids = []
    tool = mining_tool_missing(ctx)
    if tool:
        kids = [source(ctx, it, q, depth + 1) for it, q in tool]
        kids = [k for k in kids if k]
    cash = fee + sum(k["cash"] for k in kids)
    return {"how": "mine", "item": name, "qty": qty, "cash": cash, "minutes": minutes + sum(k["minutes"] for k in kids), "surplus": surplus,
            "cost": cash + ctx.isk(minutes) - surplus + sum(ctx.isk(k["minutes"]) for k in kids), "children": kids, "after": lines,
            "text": f"MINE {units:,} x {ore} (~{minutes:.0f} min{yield_note}) and REFINE it: keep {qty:,} x {name}"}


def mining_tool_missing(ctx):
    try:
        from . import tools as _tl
        if _tl.fitted_now(ctx.con).get("mining", 0) or _tl.held_anywhere(ctx.con).get("mining", 0):
            return []
        return [(it, q) for it, q in _tl.TOOLS["mining"]["buy"]]
    except Exception:                                                   # noqa: BLE001
        return []


def _build(ctx, name, qty, depth):
    """Build `qty` x name: blueprint (owned or bought) + materials (each sourced) + job fee; the batch size that costs least after selling the rest."""
    con = ctx.con
    bp = _type(con, name + " Blueprint")
    prod = _type(con, name)
    if not bp or not prod:
        return None
    mats = _q(con, "SELECT m.material_id, m.quantity, t.name FROM bp_materials m JOIN types t ON t.type_id=m.material_id WHERE m.blueprint_id=?", (bp[0],))
    out_q = _q(con, "SELECT quantity FROM bp_products WHERE blueprint_id=?", (bp[0],))
    if not mats:
        return None
    per_run = int(out_q[0][0]) if out_q and out_q[0][0] else 1
    try:
        from .skills import blueprint_missing, have
        lv = have(con)
        if lv and blueprint_missing(con, bp[0], lv):
            return None                                                 # you cannot run this blueprint yet (skills): not an option
    except Exception as _he:                                            # noqa: BLE001
        _hrec('preptree', _he)
    own = _q(con, "SELECT me FROM my_blueprints WHERE blueprint_id=? ORDER BY me DESC LIMIT 1", (bp[0],))
    me = int(own[0][0] or 0) if own else 0
    bp_node = None
    if not own:
        bp_node = _buy(ctx, bp[1], 1)
        if not bp_node:
            return None
    adj = {r[0]: float(r[1] or 0) for r in _q(con, "SELECT type_id, adjusted_price FROM prices")}
    best = None
    for runs in sorted({math.ceil(qty / per_run)} | {b for b in BATCHES if b * per_run >= qty}):
        made = runs * per_run
        kids, ok = ([bp_node] if bp_node else []), True
        for mid, q, mname in mats:
            need = max(1, math.ceil(q * runs * (1 - me / 100.0)))
            have_n = _held(ctx, mname)
            if have_n >= need:
                continue
            k = source(ctx, mname, need - have_n, depth + 1, raw_only=True)
            if not k:
                ok = False
                break
            kids.append(k)
        if not ok:
            continue
        fee = sum(q * runs * adj.get(mid, 0.0) for mid, q, _n in mats) * ctx.fee_rate
        extra = made - qty
        sale = best_bid(ctx, name, extra) if extra > 0 else (0.0, None, 0)
        cash = sum(k["cash"] for k in kids) + fee
        minutes = BUILD_MIN + sum(k["minutes"] for k in kids)
        cost = sum(k["cost"] for k in kids) + fee + ctx.isk(BUILD_MIN) - sale[0]
        if best is None or cost < best["cost"]:
            after = [f"sell the other {extra:,} x {name} at {sale[1]} (~{sale[0]:,.0f} after tax and the trip)"] if sale[1] else []
            best = {"how": "build", "item": name, "qty": qty, "runs": runs, "cash": cash, "minutes": minutes, "cost": cost, "children": kids, "after": after,
                    "text": f"BUILD {made:,} x {name} ({runs} run{'s' if runs != 1 else ''}; job fee ~{fee:,.0f})" + (f", keep {qty:,}" if extra > 0 else "")}
    return best


def source(ctx, name, qty, depth=0, raw_only=False):
    """The cheapest way to get `qty` x name -> node {how, item, qty, cash, minutes, cost, children, text} or None (no way known)."""
    key = (name.lower(), qty, raw_only)
    if key in ctx.cache:
        return ctx.cache[key]
    have_n = _held(ctx, name)
    if have_n >= qty:
        node = {"how": "held", "item": name, "qty": qty, "cash": 0.0, "minutes": 0.0, "cost": 0.0, "children": [], "text": f"{name}: you own {have_n:,} (free)"}
        ctx.cache[key] = node
        return node
    need = qty - have_n
    opts = [_buy(ctx, name, need)]
    if depth < MAX_DEPTH:
        if raw_only:
            opts.append(_mine(ctx, name, need, depth))
        else:
            opts.append(_build(ctx, name, need, depth))
    opts = [o for o in opts if o]
    node = min(opts, key=lambda o: o["cost"]) if opts else None
    if node and len(opts) > 1:
        alt = sorted(opts, key=lambda o: o["cost"])[1]
        node["beat"] = f"{alt['how']} would cost ~{alt['cost']:,.0f} ISK-equivalent"
    ctx.cache[key] = node
    return node


def leaves(node):
    """The steps in the order they are done: children first (materials before the build), the node last."""
    if not node or node["how"] == "held":
        return []
    out = []
    for k in node.get("children", []):
        out += leaves(k)
    return out + [node]


def _combat_items(con, g, p):
    try:
        from .shopping import wishes
        return [(w["item"], int(w["qty"])) for w in wishes(con, p, g) if w.get("needs_combat_hull") or str(w.get("why", "")).startswith("combat hull")]
    except Exception as _he:                                            # noqa: BLE001
        _hrec('preptree', _he)
        return []


def _tool_items(con, tool):
    try:
        from . import tools as _tl
        from .acquire import held
        if _tl.fitted_now(con).get(tool, 0):
            return []
        return [(it, q - held(con, it)) for it, q in _tl.TOOLS.get(tool, {}).get("buy", []) if held(con, it) < q]
    except Exception:                                                   # noqa: BLE001
        return []


def _spec(out, key, tool=None):
    return out.setdefault(key, {"tool": tool, "skills": [], "hull": [], "items": [], "goals": []})


def goals(con, g, p, best_min):
    """Blocked goals by prep group -> {key: {tool, skills [(name, level)], hull [names], items [(item, qty)], goals [{name, isk, minutes, modeled}]}}.
    Goals that only lack a tool share the tool's group (one combat fit opens every combat goal); a goal that also lacks skills, a hull or extra items
    (analyzers ...) gets a group of its own. Unmodeled goals are valued at best_min ISK/min."""
    out = {}
    try:
        from .nextstep import _INCLUDE_BLOCKED, _OFFERS_CACHE, _offers_rows_calc, combat_ready
        from pathlib import Path
        _INCLUDE_BLOCKED[0] = True
        _OFFERS_CACHE.clear()
        try:
            rows = _offers_rows_calc(con, g, p, Path(_ROOT) / "agent_offers.json")
        finally:
            _INCLUDE_BLOCKED[0] = False
            _OFFERS_CACHE.clear()
        ready = combat_ready(con, g, p)
        from . import tools as _tl
        fitted = _tl.fitted_now(con)
        for rate, net, minutes, o, _t in rows:
            nt = o.get("needs_tool")
            if not nt or (nt == "gun" and ready) or (nt != "gun" and fitted.get(nt)):
                continue
            mins = max(float(minutes), 1.0)
            per = max(float(net) / mins, best_min) if not o.get("timed") else float(net) / mins   # combat time is a guess until timed: best ISK/min
            _spec(out, nt, nt)["goals"].append({"name": f"{o['agent'].split(' (')[0]}: {o.get('mission', '')[:40]}", "isk": per * mins, "minutes": mins,
                                                "modeled": bool(o.get("timed"))})
    except Exception as _he:                                            # noqa: BLE001
        _hrec('preptree', _he)
    try:
        from . import combatprep
        from . import tools as _tl
        from .acquire import held
        from .allplans import COMBAT_IDS
        from .catalog import MODELED_RUNS, skill_levels, status
        from .lookahead import act_rate
        from .nextstep import combat_ready
        owned = [n for n, _s in combatprep.state(con, p)["ships"]]
        hull = getattr(p, "ship_name", "") or ""
        tools = {"fitted": _tl.fitted_now(con), "held": _tl.held_anywhere(con)}
        levels = skill_levels(con)
        ready = combat_ready(con, g, p)
        for a in status(con, float(getattr(p, "wallet_isk", 0.0) or 0.0), hull, owned, tools):
            if a.get("blocked") or not a.get("prior") or not a["prior"][1]:
                continue                                                # out of scope / no ISK (paragon, pvp goals ...)
            tool = "gun" if a.get("id") in COMBAT_IDS else a.get("needs_tool")
            skills = [(k, v) for k, v in a.get("requires", {}).items() if levels.get(k.lower(), 0) < v]
            items = [(it, q - held(con, it)) for it, q in a.get("prep_items", []) if held(con, it) < q]
            nh = a.get("needs_hull") or []
            hull_missing = [] if not nh or tool == "gun" or any(w.lower() in (hull + " " + " ".join(owned)).lower() for w in nh) else nh
            tool_open = bool(tool) and ((tool == "gun" and not ready) or (tool != "gun" and not tools["fitted"].get(tool)))
            if not (skills or items or hull_missing or tool_open):
                continue                                                # doable now: it is on the plan list already
            modeled = a.get("runs", 0) >= MODELED_RUNS
            per = act_rate(a)[0] / 60.0 if modeled else best_min
            goal = {"name": a["name"], "isk": per * ACTIVITY_MIN, "minutes": ACTIVITY_MIN, "modeled": modeled}
            if skills or items or hull_missing:
                s = _spec(out, a["id"], tool if tool_open else None)
                s.update(skills=skills, hull=hull_missing, items=items)
                s["goals"].append(goal)
            else:
                _spec(out, tool, tool)["goals"].append(goal)
    except Exception as _he:                                            # noqa: BLE001
        _hrec('preptree', _he)
    return {k: v for k, v in out.items() if v["goals"]}


def _do_step(con, g, p, grp):
    """Prep with nothing to buy: fit what you own / show the fit (combatprep, agentchain.gear_step). -> node or None."""
    txt, minutes = "", 3.0
    try:
        if grp == "gun":
            from . import combatprep
            txt = combatprep.next_step(con, g, p, lambda s, why="", *a, **k: f"STEP: FLY to {s} - {why}")
            minutes = combatprep.prep_estimate(con, g, p)[0] or minutes
        else:
            txt = f"STEP: FIT the {grp} gear you own on the ship you fly (Fitting window, drag it from cargo or the hangar onto a free slot)"
    except Exception as _he:                                            # noqa: BLE001
        _hrec('preptree', _he)
    if not txt:
        return None
    head = txt.splitlines()[0].replace("STEP: ", "")
    return {"how": "do", "item": head[:40], "qty": 1, "cash": 0.0, "minutes": float(minutes), "cost": 0.0, "children": [], "text": head, "step": txt}


def _haul_gain(con, g, p, dest):
    """Trades carried on the way to `dest` (plan_along's carry), ISK."""
    if not dest or dest == p.current_system:
        return 0.0
    try:
        from .nextstep import plan_along
        return sum(float(d.get("net", 0.0)) for d in plan_along(con, g, p, dest).get("carry", []))
    except Exception:                                                   # noqa: BLE001
        return 0.0


def chains(con, g, p, best_hr, haul=True):
    """-> [{group, goals, prep: [nodes], cash, minutes, gain, chain_min, steps}] best chain ISK/min first."""
    best_min = float(best_hr or 0.0) / 60.0
    ctx = Ctx(con, g, p, best_min)
    gs = goals(con, g, p, best_min)
    out = []
    levels = None
    for grp, spec in gs.items():
        items = spec["goals"]
        tool = spec["tool"]
        need = (_combat_items(con, g, p) if tool == "gun" else _tool_items(con, tool) if tool else []) + list(spec["items"])
        train_h, train_node = 0.0, None
        if spec["skills"]:
            if levels is None:
                from .catalog import skill_levels
                levels = skill_levels(con)
            need += [(s, 1) for s, _l in spec["skills"] if s.lower() not in levels]     # a skill you have never injected: its book is bought first
            train_h, train_node = _training(con, spec["skills"])
        nodes = [source(ctx, it, q) for it, q in need]
        if spec["hull"]:
            hulls = [n for n in (source(ctx, h, 1) for h in spec["hull"]) if n]
            nodes.append(min(hulls, key=lambda n: n["cost"]) if hulls else None)
            need.append((spec["hull"][0], 1))
        if any(n is None for n in nodes):
            missing = [it for (it, _q), n in zip(need, nodes) if n is None]
            out.append({"group": grp, "goals": items, "prep": [], "unknown": missing, "chain_min": 0.0, "rank_min": 0.0, "steps": [], "cash": 0.0, "minutes": 0.0,
                        "gain": 0.0, "train_h": train_h})
            continue
        if train_node:
            nodes.insert(0, train_node)                                 # training runs in the background: queue it first, then buy while it trains
        steps = [s for n in nodes for s in leaves(n)]
        if not steps and tool:                                          # every item owned: what is left is fitting / showing the fit (no cash, a few minutes)
            do = _do_step(con, g, p, tool)
            if do:
                nodes, steps = [do], [do]
        cash = sum(n["cash"] for n in nodes) - sum(s.get("surplus", 0.0) for s in steps)
        minutes = sum(n["minutes"] for n in nodes)
        first_dest = next((s.get("where") for s in steps if s.get("where")), None)
        gain = _haul_gain(con, g, p, first_dest) if haul else 0.0
        pay = sum(x["isk"] for x in items)
        work = sum(x["minutes"] for x in items)
        chain_min = (pay - cash + gain) / max(work + minutes, 1.0)
        out.append({"group": grp, "tool": tool, "goals": sorted(items, key=lambda x: -x["isk"] / x["minutes"]), "prep": nodes, "cash": cash, "minutes": minutes,
                    "gain": gain, "pay": pay, "work": work, "chain_min": chain_min, "train_h": train_h,
                    "rank_min": chain_min * PLAY_H / (PLAY_H + train_h),          # waiting for training: the chain pays later, so it ranks lower
                    "prep_per_min": (cash - gain) / max(work, 1.0), "steps": steps, "unknown": []})
    out.sort(key=lambda c: -_score(c))
    return out


def _training(con, skills):
    """(hours of training incl. prerequisites, a 'do' node that queues it) for [(skill, level)] (trainplan, your attributes)."""
    try:
        from .trainplan import plan_training
        res = plan_training(con, goals=[(s, lv, "prep") for s, lv in skills])
        mins = sum(x["minutes"] for x in res["steps"])
        names = ", ".join(f"{x['skill']} {x['level']}" for x in res["steps"][:6]) or ", ".join(f"{s} {lv}" for s, lv in skills)
    except Exception as _he:                                            # noqa: BLE001
        _hrec('preptree', _he)
        mins, names = 0.0, ", ".join(f"{s} {lv}" for s, lv in skills)
    h = mins / 60.0
    txt = f"QUEUE SKILLS {names} (training ~{h:,.1f} h in the background; buy the rest while it trains)"
    return h, {"how": "do", "item": "skills", "qty": 1, "cash": 0.0, "minutes": 1.0, "cost": 0.0, "children": [], "text": txt,
               "step": f"STEP: {txt}\n   Character sheet > Skills > right-click each > Train now (or add to the queue). Then  python -m eve_profit next"}


LABEL = {"gun": "COMBAT (a fit passing the 99% rule)", "mining": "MINING (mining lasers)", "salvaging": "SALVAGING (a salvager)", "scanning": "SCANNING (probe launcher + probes)"}


def _label(c):
    return LABEL.get(c["group"]) or (c["goals"][0]["name"] if c.get("goals") else c["group"])


def _score(c):
    """ISK/min a chain is ranked by: queueing skills costs nothing and blocks nothing, so that step counts the chain without the training wait."""
    s0 = c["steps"][0] if c.get("steps") else {}
    return c["chain_min"] if s0.get("item") == "skills" else c.get("rank_min", c["chain_min"])


def _tree_lines(node, ind="      "):
    if not node:
        return []
    L = [ind + node["text"] + (f"   [{node['beat']}]" if node.get("beat") else "")]
    for k in node.get("children", []):
        L += _tree_lines(k, ind + "   ")
    L += [ind + "   then " + a for a in node.get("after", [])]
    return L


def lines(con, g, p, best_hr, haul=True):
    """Text for `next --plan` and `python -m eve_profit preptree`."""
    cs = chains(con, g, p, best_hr, haul)
    if not cs:
        return ""
    best_min = float(best_hr or 0.0) / 60.0
    L = [f"PREP CHAINS (blocked goals + the cheapest way to get able to do them; time valued at {best_min:,.0f} ISK/min, the best on the list now):"]
    for c in cs:
        L.append(f"   {_label(c)}: {len(c['goals'])} goal(s)")
        if c["unknown"]:
            L.append("      no price known for: " + ", ".join(c["unknown"]) + "  (run  python -m eve_profit scan)")
            continue
        s0 = c["steps"][0] if c["steps"] else {}
        here = s0.get("how") in ("do", "build") or s0.get("jumps", 1) == 0
        sc = _score(c)
        verdict = ("BEATS the best step now: its first step joins next" if sc > best_min else
                   "TIES the best step and its first step is HERE: it joins next" if here and sc >= best_min * TIE else "below the best step now: waits")
        L.append(f"      chain {c['chain_min']:,.0f} ISK/min = (goals pay {c['pay']:,.0f} - prep cash {c['cash']:,.0f} + trades on the way {c['gain']:,.0f}) / "
                 f"({c['work']:,.0f} + {c['minutes']:,.0f} prep min)  -> {verdict}")
        if c.get("train_h"):
            L.append(f"      skills train ~{c['train_h']:,.1f} h first: ranked at {c['rank_min']:,.0f} ISK/min for the wait")
        L.append(f"      prep costs {c['prep_per_min']:,.0f} ISK per goal-minute")
        for x in c["goals"][:5]:
            L.append(f"      goal  {x['isk'] / x['minutes']:>8,.0f} ISK/min  {x['name']}" + ("" if x["modeled"] else "  (not modeled: valued at the best ISK/min)"))
        if len(c["goals"]) > 5:
            L.append(f"      ... {len(c['goals']) - 5} more goals")
        if not c["steps"]:
            L.append("      prep: nothing missing")
        for n in c["prep"]:
            L += _tree_lines(n)
    return "\n".join(L)


def first_step(con, g, p, chain, hop_to):
    """The ONE next action of a chain as step text ('' when none)."""
    if not chain or not chain["steps"]:
        return ""
    s = chain["steps"][0]
    if s["how"] == "buy":
        from .acquire import first_action
        way = {"mode": "buy", "buy": s["src"], "item": s["item"], "qty": s["qty"], "build": None, "lines": [f"prep for {_label(chain)}"]}
        return first_action(con, g, p, way, hop_to)
    if s["how"] == "mine":
        return f"STEP: {s['text']}\n   (prep for {_label(chain)}; then  python -m eve_profit next)"
    if s["how"] == "do":
        return s["step"]
    if s["how"] == "build":
        return f"STEP: {s['text']}\n   Industry window > the blueprint > Start; the materials are in your hangar. Then  python -m eve_profit next"
    return ""


def candidates(con, g, p, best_known, hop_to):
    """-> [(ISK/hr, label, step text, note)]: the first step of the best chain when the chain beats the best step now and the cash fits the wallet."""
    try:
        cs = chains(con, g, p, best_known, haul=False)
    except Exception as _he:                                            # noqa: BLE001
        _hrec('preptree', _he)
        return []
    wallet = float(getattr(p, "wallet_isk", 0.0) or 0.0)
    for c in cs:
        s0 = c["steps"][0] if c["steps"] else None
        here = s0 is not None and (s0["how"] in ("do", "build") or s0.get("jumps", 1) == 0)
        if not s0 or s0["cash"] > wallet * 0.5:
            continue
        sc = _score(c) * 60.0
        if not (sc > best_known or (here and sc >= best_known * TIE)):
            continue                                                    # unmodeled goals equal the best rate, so a chain whose first step is HERE ties and wins
        txt = first_step(con, g, p, c, hop_to)
        if txt.startswith("STEP:"):
            return [(max(sc, best_known * 1.0001 if here else 0.0), f"prep: {c['steps'][0]['item']}", txt,
                     f"prep for {_label(c)}: the whole chain makes {c['chain_min']:,.0f} ISK/min, more than the best step now")]
    return []


if __name__ == "__main__":
    import sys
    print(json.dumps({"usage": "python -m eve_profit preptree"}), file=sys.stderr)
