"""UNALLOCATED SKILL POINTS ARE A STEP: sync reads them (meta sp_unallocated). When there are enough, `next` says to spend them on the skills the plan needs, in the order
that unlocks the most (a hull with a hold, combat basics, scanning, mining). Spending is instant and free; the step disappears at the next sync once the points are gone."""
MIN_SP = 10_000
RATE = 5_500_000.0                     # a one-minute step that saves days of training: right after the model-update screens, before every other step

# (skill, target level, why), most valuable first; only the levels you do not have yet are listed
WISHES = [
    ("Gallente Hauler", 1, "unlocks the Nereus: a big hold turns the waiting courier offers into ISK"),
    ("Gallente Frigate", 3, "Incursus and Level 2 security missions"),
    ("Small Hybrid Turret", 3, "guns for Level 2 security missions and rats"),
    ("Gallente Frigate", 4, "ratting and combat anomalies"),
    ("Astrometrics", 1, "probe scanning: relic sites and the daily scan goal"),
    ("Mining", 3, "better ore yield for the mining offers"),
    ("Science", 3, "T2 invention (later)"),
    ("Industry", 3, "T2 manufacturing (later)"),
]


def unallocated(con):
    try:
        r = con.execute("SELECT value FROM meta WHERE key='sp_unallocated'").fetchone()
        return int(float(r[0])) if r else 0
    except Exception:                                                   # noqa: BLE001
        return 0


def picks(con, limit=5):
    from .catalog import skill_levels
    have = skill_levels(con)
    out = []
    for name, lvl, why in WISHES:
        if have.get(name.lower(), 0) >= lvl:
            continue
        out.append((name, lvl, why))
        if len(out) >= limit:
            break
    return out


def candidate(con):
    """(rate, step text) or None."""
    sp = unallocated(con)
    if sp < MIN_SP:
        return None
    ps = picks(con)
    if not ps:
        return None
    L = [f"STEP: SPEND YOUR {sp:,} UNALLOCATED SKILL POINTS (about 1 minute, free, instant)",
         "   DO ONLY THIS: Neocom > Character Sheet > Skills > Training Queue panel > the + button > 'Apply Skill Points'. Tick ONLY these skills (untick all the others), then Confirm:"]
    L += [f"      {n} to level {lv}: {why}" for n, lv, why in ps]
    L += ["   (skills you do not own yet need the book first: buy it, then apply; the sync afterwards tells the tool they are done)"]
    return RATE, "\n".join(L)
