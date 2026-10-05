"""Skill advisor: which skill levels to queue next, ranked by ISK/hr gained per hour of training.
For every skill whose effect the planner models, it re-runs the planner with that skill one level
higher and measures the change in the average ISK/hr of your top opportunities. Effects that are
NOT modelled (broker fees, contracts slots, standings...) are listed separately, never ranked.
Effect sizes marked ESTIMATE are rough guesses (align/speed skills)."""
import dataclasses
import math

from .graph import Graph
from .skills import have

ATTR_NAMES = {164: "charisma", 165: "intelligence", 166: "memory", 167: "perception", 168: "willpower"}
TOP_N = 10

# skill name -> (profile transform for ONE extra level, note)
EFFECTS = {
    "Accounting": (lambda p: dataclasses.replace(p, accounting_level=min(5, p.accounting_level + 1)),
                   "-11% sales tax per level"),
    "Mass Production": (lambda p: dataclasses.replace(p, mfg_slots_total=p.mfg_slots_total + 1),
                        "+1 manufacturing slot"),
    "Advanced Mass Production": (lambda p: dataclasses.replace(p, mfg_slots_total=p.mfg_slots_total + 1),
                                 "+1 manufacturing slot"),
    "Industry": (lambda p: dataclasses.replace(p, industry_level=min(5, p.industry_level + 1)),
                 "-4% build time per level"),
    "Advanced Industry": (lambda p: dataclasses.replace(p, adv_industry_level=min(5, p.adv_industry_level + 1)),
                          "-3% build time per level"),
    "Evasive Maneuvering": (lambda p: dataclasses.replace(p, secs_per_jump=p.secs_per_jump * (1 - 0.012)),
                            "ESTIMATE: faster align, ~1.2% less time per jump"),
    "Spaceship Command": (lambda p: dataclasses.replace(p, secs_per_jump=p.secs_per_jump * (1 - 0.005)),
                          "ESTIMATE: +2% agility, ~0.5% less time per jump"),
}
NOT_MODELLED = [
    ("Contracting", "more contract slots (courier/contract trading)"),
    ("Broker Relations", "lower broker fee when you place orders"),
    ("Marketing / Procurement / Visibility", "more/farther market orders"),
    ("Connections / Diplomacy", "higher effective standing with agents (LP)"),
    ("Transport Ships -> Deep Space Transport / Blockade Runner", "safer hauling of valuable cargo"),
]


def sp_for_level(rank, level):
    """Cumulative SP needed for `level` (1..5) of a skill with this rank."""
    return 0.0 if level <= 0 else 250.0 * rank * (32 ** ((level - 1) / 2))


def train_minutes(rank, level, sp_now, primary, secondary):
    """Minutes to go from `sp_now` SP (within the previous level) to the end of `level`."""
    need = sp_for_level(rank, level) - max(sp_now, sp_for_level(rank, level - 1))
    return max(0.0, need) / (primary + secondary / 2.0)


def fmt_minutes(m):
    h = m / 60
    return f"{int(h // 24)}d {int(h % 24)}h" if h >= 24 else f"{int(h)}h {int(m % 60)}m"


def _score(plan_fn, con, p):
    top = plan_fn(con, p, TOP_N, False)
    return sum(o.isk_per_hour for o in top) / TOP_N if top else 0.0


def _skill_row(con, name):
    return con.execute("SELECT type_id,skill_rank,skill_primary,skill_secondary FROM types "
                       "WHERE name=? COLLATE NOCASE", (name,)).fetchone()


def virtual_levels(con):
    """Trained levels plus whatever is already in your queue."""
    lv = {r[0]: r[1] for r in con.execute("SELECT skill_id,level FROM character_skills")}
    for r in con.execute("SELECT skill_id,level FROM skill_queue ORDER BY position"):
        lv[r[0]] = max(lv.get(r[0], 0), r[1])
    return lv


def hull_racial_skill(con, p):
    """Name of the racial Industrial skill that gives your hull its cargo bonus, if any."""
    for r in con.execute("SELECT t.name FROM type_skills s JOIN types t ON t.type_id=s.skill_id "
                         "WHERE s.type_id=?", (p.ship_type_id,)):
        if r["name"].endswith(("Industrial", "Hauler")):
            return r["name"]
    return None


STOCK_SKILLS = [("Broker Relations", 3446, "broker"), ("Trade", 3443, 4), ("Retail", 3444, 8),
                ("Wholesale", 16596, 16), ("Tycoon", 18580, 32)]


def _stock_total(res):
    return sum((d["list_net"] if d["advice"] == "LIST" else d["net"]) for d in res["sell_here"])


def stock_skill_gains(con, p):
    """One-time ISK your CURRENT hangar stock would gain from one more level of a trading skill:
    Broker Relations cuts the listing fee ~0.3%/level; Trade/Retail/Wholesale/Tycoon add market-order slots (4/8/16/32 per level),
    so more of your high-gap stacks can be listed instead of sold instantly. Per-level gains for the next level only."""
    from .along import plan_along
    from .graph import Graph
    from .skills import order_slots
    g = Graph(con)
    lv = have(con)
    try:
        base_slots = order_slots(con)
        if base_slots is None:
            return []
        base = plan_along(con, g, p, p.current_system, slots_override=base_slots)
    except Exception:
        return []
    base_total = _stock_total(base)
    out = []
    for name, sid, eff in STOCK_SKILLS:
        cur = lv.get(sid, 0)
        if cur >= 5:
            continue
        if eff == "broker":
            alt = plan_along(con, g, dataclasses.replace(p, broker_fee=max(0.0, p.broker_fee - 0.003)),
                             p.current_system, slots_override=base_slots)
        else:
            alt = plan_along(con, g, p, p.current_system, slots_override=base_slots + eff)
        out.append({"skill": name, "skill_id": sid, "have": cur, "gain": _stock_total(alt) - base_total})
    return out


def candidate_skill_ids(con, p):
    names = list(EFFECTS) + ([hull_racial_skill(con, p)] if hull_racial_skill(con, p) else [])
    names += [n for n, _, _ in STOCK_SKILLS]
    return [r[0] for n in names for r in [_skill_row(con, n)] if r]


def fill_skill_info(con, esi, type_ids):
    """Rank (attr 275) and training attributes (180/181) from ESI for skills missing them. -> count filled."""
    n = 0
    for tid in type_ids:
        r = con.execute("SELECT skill_rank FROM types WHERE type_id=?", (tid,)).fetchone()
        if r is None or r[0]:
            continue
        try:
            attrs = {x["attribute_id"]: x["value"] for x in esi.type_info(tid).get("dogma_attributes", [])}
        except Exception:
            continue
        if 275 in attrs:
            con.execute("UPDATE types SET skill_rank=?,skill_primary=?,skill_secondary=? WHERE type_id=?",
                        (attrs[275], int(attrs.get(180, 0)), int(attrs.get(181, 0)), tid))
            n += 1
    con.commit()
    return n


def advise(con, p, plan_fn, hours=72.0):
    """-> dict(steps=[...], unmodelled=[...], notes=[...]). Each step: skill, level, minutes, gain, per_hour."""
    attrs = {r[0]: r[1] for r in con.execute("SELECT attr,value FROM char_attrs")}
    levels, notes = virtual_levels(con), []
    if not attrs:
        notes.append("No training attributes synced - run `sync` (after logging in again) for real training times.")
    base = _score(plan_fn, con, p)
    effects = dict(EFFECTS)
    racial = hull_racial_skill(con, p)
    if racial:
        def cargo(pp, name=racial):
            lvl = levels.get(_skill_row(con, name)[0], 0) if _skill_row(con, name) else 0
            return dataclasses.replace(pp, cargo_m3=pp.cargo_m3 * (1 + 0.05 * (min(5, lvl) + 1)) / (1 + 0.05 * min(5, lvl)))
        effects[racial] = (cargo, "+5% cargo hold per level")
    chains = []
    sp_now = {r[0]: r[1] for r in con.execute("SELECT skill_id,sp FROM character_skills")}
    for name, (fx, why) in effects.items():
        row = _skill_row(con, name)
        if not row or not row["skill_rank"]:
            continue
        sid, cur = row["type_id"], levels.get(row["type_id"], 0)
        if cur >= 5:
            continue
        missing = [(r[0], r[1]) for r in con.execute("SELECT skill_id,level FROM type_skills WHERE type_id=?", (sid,))
                   if levels.get(r[0], 0) < r[1]]
        if missing and cur == 0:
            notes.append(f"{name}: prerequisites not met yet ({len(missing)} missing) - train those first.")
            continue
        gain = _score(plan_fn, con, fx(p)) - base
        if gain <= 0:
            notes.append(f"{name}: no measurable ISK/hr gain right now ({why}) - not worth queueing for money.")
            continue
        prim = attrs.get(ATTR_NAMES.get(row["skill_primary"], ""), 20)
        sec = attrs.get(ATTR_NAMES.get(row["skill_secondary"], ""), 20)
        steps = []
        for lvl in range(cur + 1, 6):
            mins = train_minutes(row["skill_rank"], lvl, sp_now.get(sid, 0) if lvl == cur + 1 else 0, prim, sec)
            steps.append({"skill": name, "level": lvl, "minutes": mins, "gain": gain, "why": why})
        chains.append(steps)
    chosen, used = [], 0.0
    while chains and used < hours * 60:           # greedy: best gain per training-hour among next steps
        best = max(chains, key=lambda c: c[0]["gain"] / max(c[0]["minutes"], 1e-9))
        step = best.pop(0)
        step["per_hour"] = step["gain"] / max(step["minutes"] / 60, 1e-9)
        chosen.append(step)
        used += step["minutes"]
        if not best:
            chains.remove(best)
    stock = []
    for d in stock_skill_gains(con, p):
        row = _skill_row(con, d["skill"])
        if not row or not row["skill_rank"] or d["gain"] <= 0:
            continue
        prim = attrs.get(ATTR_NAMES.get(row["skill_primary"], ""), 20)
        sec = attrs.get(ATTR_NAMES.get(row["skill_secondary"], ""), 20)
        mins = train_minutes(row["skill_rank"], d["have"] + 1, sp_now.get(d["skill_id"], 0), prim, sec)
        stock.append(dict(d, level=d["have"] + 1, minutes=mins, per_day=d["gain"] / max(mins / 1440, 1e-9)))
    stock.sort(key=lambda d: -d["per_day"])
    trade_levels = {n: levels.get(sid, 0) for n, sid, _ in STOCK_SKILLS}
    return {"trade_levels": trade_levels, "steps": chosen, "stock": stock, "unmodelled": NOT_MODELLED, "notes": notes, "base": base, "total_minutes": used}


def format_advice(res):
    lines = [f"Current average of your top {TOP_N}: {res['base']:,.0f} ISK/hr", ""]
    if not res["steps"]:
        lines.append("Nothing measurable to queue (everything modelled is maxed, or data missing).")
    else:
        lines.append(f"{'#':>2}  {'skill':<30} {'lvl':>3} {'train':>8}  {'+ISK/hr':>10}  {'+ISK/hr per training hr':>24}  why")
        t = 0.0
        for i, s in enumerate(res["steps"], 1):
            t += s["minutes"]
            lines.append(f"{i:>2}  {s['skill']:<30} {s['level']:>3} {fmt_minutes(s['minutes']):>8}  "
                         f"{s['gain']:>10,.0f}  {s['per_hour']:>24,.0f}  {s['why']}   (queue ends in {fmt_minutes(t)})")
    if res.get("stock"):
        lines += ["", "ONE-TIME gain on the stock you hold here right now (listing instead of selling instantly):",
                  f"   {'skill':<18} {'lvl':>3} {'train':>8} {'+ISK now':>13} {'per training day':>18}"]
        for d in res["stock"]:
            lines.append(f"   {d['skill']:<18} {d['level']:>3} {fmt_minutes(d['minutes']):>8} {d['gain']:>13,.0f} {d['per_day']:>18,.0f}")
    tl = res.get("trade_levels")
    if tl:
        lines += ["", "Your trading skills (levels incl. queue): " + ", ".join(f"{n} {v}" for n, v in tl.items())
                  + ("   -> all at V: nothing to gain here" if all(v >= 5 for v in tl.values()) else "")]
    lines += ["", "Worth training but not measured by the planner:"] + [f"  - {n}: {w}" for n, w in res["unmodelled"]]
    lines += [""] + [f"NOTE: {n}" for n in res["notes"]]
    return "\n".join(lines)
