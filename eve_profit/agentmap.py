"""`agents --within N`: every mission agent within N safe jumps, grouped by the DIRECTION you would leave in (the first system on the way), from the game's static
data (no screenshots). Shows level, division (Security = combat), corporation, station, jumps and your standing with them. What it can NOT show: open offers / mission
text (the game gives those only when you dock at the agent's station: that stays a screenshot)."""
DIVISIONS = {18: "Administration", 19: "Advisory", 20: "Archives", 21: "Astrosurveying", 22: "Command", 23: "Distribution", 24: "Financial", 25: "Intelligence",
             26: "Internal Security", 27: "Legal", 28: "Manufacturing", 29: "Marketing", 30: "Mining", 31: "Personnel", 32: "Production", 33: "Public Relations",
             34: "R&D", 35: "Security", 36: "Storage", 37: "Surveillance"}
DEFAULT_MAP = {35: "Security", 30: "Mining", 23: "Distribution"}      # a guess: calibrate() replaces it with what the game data really says
USEFUL = tuple(DEFAULT_MAP)
MAP_KEY = "division_map"
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


def resolve_station_names(con, esi, station_ids):
    """Station names the static data did not carry: public /universe/names/, written into stations.name."""
    need = [i for i in set(station_ids) if not (con.execute("SELECT name FROM stations WHERE station_id=?", (i,)).fetchone() or [""])[0]]
    for k in range(0, len(need), 500):
        try:
            for x in esi.post_json("/universe/names/", need[k:k + 500]):
                con.execute("UPDATE stations SET name=? WHERE station_id=?", (x["name"], x["id"]))
        except Exception:                                               # noqa: BLE001
            break
    con.commit()


def collect(con, g, p, within=5, max_level=2, divisions=None):
    """-> {first hop system: [agent dict]} for safe systems within `within` jumps."""
    cur = g.id_of(p.current_system)
    reach = g.reach(cur, within, p.avoid_yellow)
    standing = {r[0]: r[1] for r in con.execute("SELECT from_id,standing FROM standings")}
    names = {r[0]: r[1] for r in con.execute("SELECT agent_id,name FROM agent_names")}
    cols = {r[1] for r in con.execute("PRAGMA table_info(agents)")}
    if "division_id" not in cols:
        return {}
    dmap = get_map(con)
    q = ",".join(str(int(d)) for d in (divisions or dmap))
    out, hop_cache = {}, {}
    for r in con.execute(f"SELECT agent_id,corporation_id,location_id,system_id,level,division_id FROM agents WHERE level<=? AND division_id IN ({q}) AND agent_type=2", (max_level,)):
        sid = r["system_id"]
        if sid not in reach or g.sec[sid] < SAFE:
            continue
        if r["level"] >= 2 and max(standing.get(r["agent_id"], -10.0), standing.get(r["corporation_id"], -10.0)) < 1.0:
            continue                                                    # level 2 needs standing 1.0 with the agent or its corporation
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
                                        "division": dmap.get(r["division_id"], DIVISIONS.get(r["division_id"], str(r["division_id"]))), "system": g.name[sid], "jumps": reach[sid].jumps,
                                        "sec": g.sec[sid], "station": (st[0] if st else ""), "standing": standing.get(r["agent_id"])})
    for v in out.values():
        v.sort(key=lambda a: (a["jumps"], a["division"], a["level"]))
    return out


def report(con, g, p, esi=None, within=5, max_level=2):
    cols = {r[1] for r in con.execute("PRAGMA table_info(agents)")}
    if "division_id" not in cols or not con.execute("SELECT COUNT(*) FROM agents WHERE division_id IS NOT NULL").fetchone()[0]:
        return ("The agent table has no divisions yet: run  python -m eve_profit universe --force  once to re-import the game data (it prints agent_fields and agents_with_division), then  agents --within 5  again.")
    if esi is not None and not con.execute("SELECT 1 FROM meta WHERE key=?", (MAP_KEY,)).fetchone():
        calibrate(con, esi)                                             # learn which division ids are Security / Mining / Distribution from agents we know
    if esi is not None:                                                 # names for every agent and station in reach (the planner docks at them), before the list is built
        try:
            reach_ = g.reach(g.id_of(p.current_system), within, p.avoid_yellow)
            insys = ",".join(str(int(x)) for x in reach_)
            resolve_station_names(con, esi, [r[0] for r in con.execute(f"SELECT DISTINCT location_id FROM agents WHERE level<=2 AND agent_type=2 AND system_id IN ({insys})")])
            resolve_names(con, esi, [r[0] for r in con.execute(f"SELECT agent_id FROM agents WHERE level<=2 AND agent_type=2 AND system_id IN ({insys})")][:2000])
        except Exception:                                               # noqa: BLE001
            pass
    d = collect(con, g, p, within, max_level)
    if esi is not None:
        names = resolve_names(con, esi, [a["id"] for v in d.values() for a in v])
        for v in d.values():
            for a in v:
                a["name"] = names.get(a["id"], a["name"])
    L = [f"MISSION AGENTS within {within} safe jumps of {p.current_system} (level <= {max_level}; Security = combat, Mining, Distribution), grouped by the way you leave:", ""]
    for hop in sorted(d, key=lambda h: min(a["jumps"] for a in d[h])):
        v = d[hop]
        L.append(f"DIRECTION {hop}  ({len(v)} agents)")
        shown, per_div = [], {}
        for a in v:                                                     # at most 4 per division, nearest first: Distribution must not hide Security and Mining
            per_div[a["division"]] = per_div.get(a["division"], 0) + 1
            if per_div[a["division"]] <= 4:
                shown.append(a)
        for a in shown:
            s = f"{a['standing']:+.1f}" if a["standing"] is not None else "  - "
            L.append(f"   {a['jumps']} jump(s)  {a['system']:<12} {a['sec']:.1f}  L{a['level']} {a['division']:<12} {a['name']:<24} standing {s}  {a['station'][:48]}")
        if len(v) > len(shown):
            L.append(f"   ... and {len(v) - len(shown)} more (4 per division shown)")
        L.append("")
    if not d:
        L.append("   none found")
    L.append("Open offers and the mission text are only visible when you dock at the agent's station (game limit): that is the one thing that stays a screenshot.")
    return "\n".join(L)


def known_names():
    """[(agent name, type)] of the agents we have seen in the game (mission_agents.json / agents_nearby.json / agent_offers.json): the ground truth for the division ids."""
    import json
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = []

    def load(name):
        try:
            return json.load(open(os.path.join(root, name), encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    for a in load("mission_agents.json").get("agents", []):
        if a.get("name") and a.get("type") in ("Security", "Mining", "Distribution"):
            out.append((a["name"], a["type"]))
    d = load("agents_nearby.json")
    for key, typ in (("security", "Security"), ("mining", "Mining"), ("distribution_nearest", "Distribution")):
        out += [(a["agent"], typ) for a in d.get(key, []) if a.get("agent")]
    return list(dict.fromkeys(out))


def calibrate(con, esi):
    """Which division_id is Security / Mining / Distribution? Ask the game API for the ids of agents we KNOW (public /universe/ids/), read their division from the data,
    vote. Stored in meta 'division_map'. -> {division_id: type} (empty when the API could not be reached)."""
    import json
    names = known_names()
    if not names:
        return {}
    try:
        res = esi.post_json("/universe/ids/", [n for n, _ in names][:500])
    except Exception:                                                   # noqa: BLE001
        return {}
    ids = {c["name"]: c["id"] for c in res.get("characters", []) + res.get("agents", [])}
    votes = {}
    for n, typ in names:
        if n in ids:
            r = con.execute("SELECT division_id FROM agents WHERE agent_id=?", (ids[n],)).fetchone()
            if r and r[0] is not None:
                votes.setdefault(r[0], {}).setdefault(typ, 0)
                votes[r[0]][typ] += 1
    mapping = {int(div): max(v, key=v.get) for div, v in votes.items()}
    if mapping:
        con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (MAP_KEY, json.dumps(mapping)))
        con.commit()
    return mapping


def get_map(con):
    import json
    try:
        r = con.execute("SELECT value FROM meta WHERE key=?", (MAP_KEY,)).fetchone()
        m = {int(k): v for k, v in json.loads(r[0]).items()} if r else {}
    except Exception:                                                   # noqa: BLE001
        m = {}
    return m or dict(DEFAULT_MAP)
