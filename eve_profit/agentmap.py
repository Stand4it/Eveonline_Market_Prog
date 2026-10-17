"""`agents --within N`: every mission agent within N safe jumps, grouped by the DIRECTION you would leave in (the first system on the way), from the game's static
data (no screenshots). Shows level, division (Security = combat), corporation, station, jumps and your standing with them. What it can NOT show: open offers / mission
text (the game gives those only when you dock at the agent's station: that stays a screenshot)."""
DIVISIONS = {18: "Administration", 19: "Advisory", 20: "Archives", 21: "Astrosurveying", 22: "Command", 23: "Distribution", 24: "Financial", 25: "Intelligence",
             26: "Internal Security", 27: "Legal", 28: "Manufacturing", 29: "Marketing", 30: "Mining", 31: "Personnel", 32: "Production", 33: "Public Relations",
             34: "R&D", 35: "Security", 36: "Storage", 37: "Surveillance"}
USEFUL = (23, 30, 35)                 # Distribution, Mining, Security: the mission types the planner knows how to run
SAFE = 0.5


def resolve_names(con, esi, ids):
    """Agent names from the public ESI /universe/names/ (cached in agent_names). -> {id: name}."""
    have = {r[0]: r[1] for r in con.execute("SELECT agent_id,name FROM agent_names")}
    need = [i for i in ids if i not in have]
    for k in range(0, len(need), 500):
        try:
            for x in esi.post_json("/universe/names/", need[k:k + 500]):
                have[x["id"]] = x["name"]
                con.execute("INSERT OR REPLACE INTO agent_names VALUES(?,?)", (x["id"], x["name"]))
        except Exception:                                               # noqa: BLE001
            break
    con.commit()
    return have


def collect(con, g, p, within=5, max_level=2, divisions=USEFUL):
    """-> {first hop system: [agent dict]} for safe systems within `within` jumps."""
    cur = g.id_of(p.current_system)
    reach = g.reach(cur, within, p.avoid_yellow)
    standing = {r[0]: r[1] for r in con.execute("SELECT from_id,standing FROM standings")}
    names = {r[0]: r[1] for r in con.execute("SELECT agent_id,name FROM agent_names")}
    cols = {r[1] for r in con.execute("PRAGMA table_info(agents)")}
    if "division_id" not in cols:
        return {}
    q = ",".join(str(int(d)) for d in divisions)
    out, hop_cache = {}, {}
    for r in con.execute(f"SELECT agent_id,corporation_id,location_id,system_id,level,division_id FROM agents WHERE level<=? AND division_id IN ({q}) AND agent_type=2", (max_level,)):
        sid = r["system_id"]
        if sid not in reach or g.sec[sid] < SAFE:
            continue
        if sid == cur:
            hop = "(this system)"
        else:
            if sid not in hop_cache:
                try:
                    path = g.route(cur, sid, 60, p.avoid_yellow).path
                    hop_cache[sid] = g.name[path[1]] if len(path) > 1 else g.name[sid]
                except Exception:                                       # noqa: BLE001
                    hop_cache[sid] = g.name[sid]
            hop = hop_cache[sid]
        st = con.execute("SELECT name FROM stations WHERE station_id=?", (r["location_id"],)).fetchone()
        out.setdefault(hop, []).append({"id": r["agent_id"], "name": names.get(r["agent_id"], f"agent {r['agent_id']}"), "level": r["level"],
                                        "division": DIVISIONS.get(r["division_id"], str(r["division_id"])), "system": g.name[sid], "jumps": reach[sid].jumps,
                                        "sec": g.sec[sid], "station": (st[0] if st else ""), "standing": standing.get(r["agent_id"])})
    for v in out.values():
        v.sort(key=lambda a: (a["jumps"], a["division"], a["level"]))
    return out


def report(con, g, p, esi=None, within=5, max_level=2):
    cols = {r[1] for r in con.execute("PRAGMA table_info(agents)")}
    if "division_id" not in cols or not con.execute("SELECT COUNT(*) FROM agents WHERE division_id IS NOT NULL").fetchone()[0]:
        return ("The agent table has no divisions yet: run  python -m eve_profit universe --force  once to re-import the game data (it prints agent_fields and agents_with_division), then  agents --within 5  again.")
    d = collect(con, g, p, within, max_level)
    if esi is not None:
        ids = [a["id"] for v in d.values() for a in v]
        names = resolve_names(con, esi, ids)
        for v in d.values():
            for a in v:
                a["name"] = names.get(a["id"], a["name"])
    L = [f"MISSION AGENTS within {within} safe jumps of {p.current_system} (level <= {max_level}; Security = combat, Mining, Distribution), grouped by the way you leave:", ""]
    for hop in sorted(d, key=lambda h: min(a["jumps"] for a in d[h])):
        v = d[hop]
        L.append(f"DIRECTION {hop}  ({len(v)} agents)")
        for a in v[:14]:
            s = f"{a['standing']:+.1f}" if a["standing"] is not None else "  - "
            L.append(f"   {a['jumps']} jump(s)  {a['system']:<12} {a['sec']:.1f}  L{a['level']} {a['division']:<12} {a['name']:<24} standing {s}  {a['station'][:48]}")
        if len(v) > 14:
            L.append(f"   ... and {len(v) - 14} more")
        L.append("")
    if not d:
        L.append("   none found")
    L.append("Open offers and the mission text are only visible when you dock at the agent's station (game limit): that is the one thing that stays a screenshot.")
    return "\n".join(L)
