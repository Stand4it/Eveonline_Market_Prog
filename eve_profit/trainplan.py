"""`trainplan`: what to train RIGHT NOW, then next, then next, from THIS character's actual skills.
Goals are in a default order for a multi-career character (safe money first: trading and hauling, then combat basics,
exploration, mining). Prerequisites are pulled in from the game data, so every line is trainable when its turn comes.
The planner-driven `skills` advice takes over once the character has ISK and opportunities to measure."""
from .advisor import ATTR_NAMES, _skill_row, fmt_minutes, train_minutes, virtual_levels

GOALS = [
    ("Trade", 3, "more market orders; prerequisite for the tax/fee skills"),
    ("Accounting", 3, "lower sales tax on everything you sell"),
    ("Broker Relations", 3, "lower fee on every sell/buy order you place"),
    ("Gallente Hauler", 2, "fly the Iteron hauler; +5% cargo per level"),
    ("Gallente Frigate", 3, "fly Gallente frigates for missions and ratting"),
    ("Retail", 2, "more simultaneous market orders"),
    ("Mechanics", 3, "tougher hull for combat and mining"),
    ("Light Drone Operation", 3, "drones: easy damage for a new pilot"),
    ("Small Hybrid Turret", 3, "guns for Gallente frigates"),
    ("Evasive Maneuvering", 3, "faster align: less time and risk per jump"),
    ("Contracting", 2, "more contract slots (courier and item contracts)"),
    ("Astrometrics", 3, "scan sites: exploration income"),
    ("Archaeology", 2, "relic sites (exploration)"),
    ("Hacking", 2, "data sites (exploration)"),
    ("Mining", 3, "ore mining yield"),
    ("Accounting", 4, "lower sales tax again"),
    ("Broker Relations", 4, "lower broker fee again"),
    ("Retail", 4, "more simultaneous market orders"),
    ("Gallente Hauler", 3, "+5% cargo per level"),
]


def _need(con, levels, sid, lvl, out, seen):
    """Append (skill_id, level) steps so skill `sid` reaches `lvl`, prerequisites first."""
    for pre, plvl in con.execute("SELECT skill_id,level FROM type_skills WHERE type_id=?", (sid,)).fetchall():
        _need(con, levels, pre, plvl, out, seen)
    for l in range(levels.get(sid, 0) + 1, lvl + 1):
        if (sid, l) not in seen:
            seen.add((sid, l))
            out.append((sid, l))
    levels[sid] = max(levels.get(sid, 0), lvl)


def plan_training(con, hours=24.0, goals=GOALS):
    levels = virtual_levels(con)                  # trained levels plus what is already queued
    attrs = {r[0]: r[1] for r in con.execute("SELECT attr,value FROM char_attrs")}
    sp_now = {r[0]: r[1] for r in con.execute("SELECT skill_id,sp FROM character_skills")}
    steps, seen, why_of = [], set(), {}
    for name, lvl, why in goals:
        row = _skill_row(con, name)
        if not row:
            continue
        before = len(steps)
        _need(con, levels, row["type_id"], lvl, steps, seen)
        for sid, l in steps[before:]:
            why_of[(sid, l)] = why if sid == row["type_id"] else f"prerequisite for {name}"
    out, used, unknown = [], 0.0, []
    for sid, l in steps:
        r = con.execute("SELECT name,skill_rank,skill_primary,skill_secondary FROM types WHERE type_id=?", (sid,)).fetchone()
        if not r or not r["skill_rank"]:
            unknown.append(r["name"] if r else str(sid))
            continue
        prim = attrs.get(ATTR_NAMES.get(r["skill_primary"], ""), 20)
        sec = attrs.get(ATTR_NAMES.get(r["skill_secondary"], ""), 20)
        mins = train_minutes(r["skill_rank"], l, sp_now.get(sid, 0), prim, sec)
        used += mins
        out.append({"skill": r["name"], "level": l, "minutes": mins, "cum": used, "why": why_of.get((sid, l), "")})
    return {"steps": out, "unknown": sorted(set(unknown)), "have_attrs": bool(attrs), "hours": hours}


def format_trainplan(res):
    limit = res["hours"] * 60
    L = ["TRAINING PLAN for this character (default order: safe money first, then combat basics, exploration, mining):", ""]
    shown = 0
    for i, s in enumerate(res["steps"], 1):
        if s["cum"] - s["minutes"] >= limit and shown >= 1:
            break
        shown += 1
        L.append(f" {i:>2}. {s['skill']} {s['level']:<2} {fmt_minutes(s['minutes']):>8}   (total {fmt_minutes(s['cum']):>8})  {s['why']}")
    rest = len(res["steps"]) - shown
    if rest > 0:
        L.append(f"     ...{rest} more steps after this (run with a bigger --hours to see them)")
    L += ["", "In game: Neocom > Character Sheet > Skills > Skill Catalogue (set 'Can train now'), press + on each skill, in this order.",
          "Queue at least as many hours as you will be away. An empty queue wastes training time."]
    if not res["have_attrs"]:
        L.append("Training times assume average attributes: run `login` then `sync` for exact ones.")
    if res["unknown"]:
        L.append("Times unknown (rank missing in the data) for: " + ", ".join(res["unknown"][:8]))
    return "\n".join(L)
