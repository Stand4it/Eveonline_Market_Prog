"""`diag`: print what the program believes about your ship and skills, to debug odd numbers."""


def diagnose(con, p):
    L = [f"Ship in profile: {p.ship_name!r}  type_id={p.ship_type_id}  cargo_m3={p.cargo_m3:,.1f}"]
    t = con.execute("SELECT name,capacity,volume,category_id FROM types WHERE type_id=?", (p.ship_type_id,)).fetchone()
    L.append(f"types row: {dict(t) if t else 'MISSING (type not in database)'}")
    reqs = con.execute("SELECT s.skill_id,s.level,t.name FROM type_skills s LEFT JOIN types t ON t.type_id=s.skill_id "
                       "WHERE s.type_id=?", (p.ship_type_id,)).fetchall()
    L.append(f"required skills stored for this hull: {len(reqs)}")
    have = {r[0]: r[1] for r in con.execute("SELECT skill_id,level FROM character_skills")}
    for r in reqs:
        L.append(f"   {r['name']} (id {r['skill_id']}) needs {r['level']}, you have {have.get(r['skill_id'], 'not trained')}")
    L.append(f"skills synced: {len(have)}   skill-queue rows: {con.execute('SELECT COUNT(*) FROM skill_queue').fetchone()[0]}"
             f"   attributes: {dict(con.execute('SELECT attr,value FROM char_attrs').fetchall())}")
    ranks = con.execute("SELECT COUNT(*) FROM types WHERE skill_rank IS NOT NULL").fetchone()[0]
    L.append(f"skill types with a rank (needed by the advisor): {ranks}")
    L.append(f"type_skills rows total: {con.execute('SELECT COUNT(*) FROM type_skills').fetchone()[0]}   "
             f"ships parked: {con.execute('SELECT COUNT(*) FROM my_ships').fetchone()[0]}")
    return "\n".join(L)
