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


def book_list(con, g, p, res, hours=None):
    """Skill books to BUY first: skills in the plan you have never trained (no row in your skills = no book trained yet).
    Priced at the cheapest sell order within 10 jumps. -> [(skill, price, system, jumps)]; price None = no seller found."""
    owned = {r[0] for r in con.execute("SELECT skill_id FROM character_skills")}
    reach = g.reach(g.id_of(p.current_system), 10, p.avoid_yellow) if p.current_system in {g.name[s] for s in g.name} else {}
    limit = (hours or res["hours"]) * 60
    out, seen = [], set()
    for st in res["steps"]:
        if st["cum"] - st["minutes"] >= limit and out:
            break
        if st["level"] != 1 or st["skill"] in seen:
            continue
        row = con.execute("SELECT type_id FROM types WHERE name=? COLLATE NOCASE", (st["skill"],)).fetchone()
        if not row or row[0] in owned:
            continue
        seen.add(st["skill"])
        best = None
        for sysid, price in con.execute("SELECT system_id,MIN(price) FROM orders WHERE type_id=? AND is_buy=0 GROUP BY system_id", (row[0],)):
            if sysid in reach and (best is None or price < best[0]):
                best = (price, sysid)
        out.append((st["skill"], best[0] if best else None, g.name[best[1]] if best else "", reach[best[1]].jumps if best else 0))
    return out


def trainable_now(con, res):
    """Plan steps you can queue TODAY without buying anything: the skill already has a row in your skills (its book is trained),
    so the next level is just a click. A level-1 step of a skill you never trained needs the book first, so it is not here."""
    owned = {r[0] for r in con.execute("SELECT skill_id FROM character_skills")}
    out = []
    for st in res["steps"]:
        row = con.execute("SELECT type_id FROM types WHERE name=? COLLATE NOCASE", (st["skill"],)).fetchone()
        if row and row[0] in owned:
            out.append(st)
    return out


def format_top3(con, g, p, res):
    """Two short lists at the top of `trainplan`: the 3 best skills for you (book or not) and the 3 you can queue RIGHT NOW."""
    books = {n: (price, where, jumps) for n, price, where, jumps in book_list(con, g, p, res, hours=10 ** 6)}
    owned = {r[0] for r in con.execute("SELECT skill_id FROM character_skills")}

    def have(st):
        row = con.execute("SELECT type_id FROM types WHERE name=? COLLATE NOCASE", (st["skill"],)).fetchone()
        return bool(row and row[0] in owned)

    def line(i, st):
        b = books.get(st["skill"])
        if have(st) or not b or st["level"] != 1:
            tag = "you can queue it now" if have(st) else "needs its book first (bought for an earlier level)"
        else:
            tag = (f"BOOK NEEDED: ~{b[0]:,.0f} ISK at {b[1]} ({b[2]} jumps)" if b[0] else "BOOK NEEDED: no seller found nearby")
        return f" {i}. {st['skill']} {st['level']}  ({fmt_minutes(st['minutes'])})  {st['why']}  [{tag}]"

    L = ["TOP 3 RECOMMENDED (best for you, whether or not you own the book):"]
    L += [line(i, st) for i, st in enumerate(res["steps"][:3], 1)] or [" (nothing planned)"]
    now = trainable_now(con, res)[:3]
    L += ["", "TOP 3 YOU CAN TRAIN RIGHT NOW (no purchase needed):"]
    L += [line(i, st) for i, st in enumerate(now, 1)] or [" (none: every skill in your plan needs a new book - buy the first one above)"]
    return "\n".join(L)


def format_books(books, wallet):
    if not books:
        return ""
    total = sum(b[1] for b in books if b[1])
    L = ["", "BUY THESE SKILL BOOKS FIRST (you have never trained them, so you probably do not own the book; skip any you already have):"]
    for name, price, where, jumps in books:
        L.append(f"   {name:<26} " + (f"~{price:>10,.0f} ISK at {where} ({jumps} jumps)" if price else "no seller found nearby: check the market in game"))
    L.append(f"   total about {total:,.0f} ISK; your wallet {wallet:,.0f} ISK" + ("" if total <= wallet else "  <- NOT ENOUGH: buy the first ones only"))
    L.append("   Market > Skills (or search the name) > Buy. Then queue them, and spend your unallocated skill points on the first ones.")
    return "\n".join(L)


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
