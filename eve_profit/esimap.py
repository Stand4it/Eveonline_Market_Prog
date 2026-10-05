"""Build the star map around your system straight from ESI (no SDE download needed).
Per system: /universe/systems/{id} -> name, security, constellation, stargates;
/universe/stargates/{id} -> destination; /universe/constellations/{id} -> region."""
from concurrent.futures import ThreadPoolExecutor


def find_system_id(esi, name):
    res = esi.post_json("/universe/ids/", [name])
    systems = res.get("systems") or []
    if not systems:
        raise RuntimeError(f"ESI doesn't know a system called '{name}'")
    return systems[0]["id"]


def build_map(con, esi, start_name, depth=6, workers=8, log=print):
    """Breadth-first from `start_name`, `depth` jumps. -> (systems, gates)."""
    start = find_system_id(esi, start_name)
    seen, frontier, region_of = {start}, [start], {}
    gates = set()
    pool = ThreadPoolExecutor(workers)

    def sysinfo(sid):
        return sid, esi.get(f"/universe/systems/{sid}/")[0]

    def gate(gid):
        return esi.get(f"/universe/stargates/{gid}/")[0]

    def region(cid):
        if cid not in region_of:
            region_of[cid] = esi.get(f"/universe/constellations/{cid}/")[0]["region_id"]
        return region_of[cid]

    for d in range(depth + 1):
        infos = list(pool.map(sysinfo, frontier))
        for sid, info in infos:
            con.execute("INSERT OR REPLACE INTO systems VALUES(?,?,?,?)",
                        (sid, info["name"], info.get("security_status", 0.0), region(info["constellation_id"])))
        nxt = []
        if d < depth:                      # last layer: record the systems but don't expand
            gids = [(sid, g) for sid, info in infos for g in info.get("stargates", [])]
            for (sid, _), g in zip(gids, pool.map(gate, [g for _, g in gids])):
                dest = g["destination"]["system_id"]
                gates.add((sid, dest))
                if dest not in seen:
                    seen.add(dest)
                    nxt.append(dest)
        log(f"  jump {d}: {len(infos)} systems")
        frontier = nxt
        if not frontier:
            break
    con.executemany("INSERT OR IGNORE INTO gates VALUES(?,?)", list(gates))
    con.commit()
    return len(seen), len(gates)
