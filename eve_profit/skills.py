"""Skill and manufacturing-slot checks. If no skills were synced (no login yet) checks are
skipped, not failed, so offline/mock use keeps working."""
MASS_PRODUCTION, ADV_MASS_PRODUCTION = 3387, 24625


def have(con):
    return {r[0]: r[1] for r in con.execute("SELECT skill_id,level FROM character_skills")}


def missing(reqs, have_levels):
    """reqs: iterable of (skill_id, level) -> [(skill_id, need, have)] not yet satisfied."""
    return [(s, lvl, have_levels.get(s, 0)) for s, lvl in reqs if have_levels.get(s, 0) < lvl]


def skill_name(con, sid):
    r = con.execute("SELECT name FROM types WHERE type_id=?", (sid,)).fetchone()
    return r[0] if r else f"skill {sid}"


def explain(con, miss):
    return ", ".join(f"{skill_name(con, s)} {need} (have {h})" for s, need, h in miss)


def free_slots(p):
    return max(0, p.mfg_slots_total - p.mfg_slots_used)


def blueprint_missing(con, bp, have_levels):
    reqs = con.execute("SELECT skill_id,level FROM skill_reqs WHERE blueprint_id=?", (bp,)).fetchall()
    return missing([(r[0], r[1]) for r in reqs], have_levels)


def type_missing(con, type_id, have_levels):
    reqs = con.execute("SELECT skill_id,level FROM type_skills WHERE type_id=?", (type_id,)).fetchall()
    return missing([(r[0], r[1]) for r in reqs], have_levels)


def blocked_blueprints(con, p, limit=5):
    """Builds you'd rank if you had the skills: [(product name, 'Skill N (have M)')]."""
    h = have(con)
    if not h:
        return []
    mine = "" if p.assume_all_blueprints else " WHERE b.blueprint_id IN (SELECT blueprint_id FROM my_blueprints)"
    out = []
    for r in con.execute("SELECT b.blueprint_id,t.name FROM bp_products b JOIN types t "
                         "ON t.type_id=b.product_id" + mine):
        m = blueprint_missing(con, r[0], h)
        if m:
            out.append((r[1], explain(con, m)))
    return out[:limit]
