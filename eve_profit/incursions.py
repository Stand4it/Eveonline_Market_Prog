"""INCURSIONS (Sansha) from the game, by program: ESI /incursions/ is public and lists every active incursion (constellation, staging system, state, influence, boss).
The other Encounters cards (Crimson Harvest, Homefront Operations, Pirate Strongholds, Abyssal Deadspace) have no agents and no ESI list: they stay catalog entries.
Incursion sites are FLEET content (a fleet of strong ships, not solo and not for a frigate or a capsule), so they are listed for the model, never routed as a step."""
import json

KEY = "incursions"


def fetch(con, esi):
    """Read the active incursions and keep them in meta. -> (summary, share changed, expires)."""
    data, _pages = esi.get("/incursions/")
    old = {i.get("constellation_id") for i in _load(con)}
    con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (KEY, json.dumps(data)))
    con.commit()
    new = {i.get("constellation_id") for i in data}
    frac = len(new ^ old) / float(max(len(new | old), 1))
    return f"{len(data)} active incursions", frac, None


def _load(con):
    try:
        r = con.execute("SELECT value FROM meta WHERE key=?", (KEY,)).fetchone()
        return json.loads(r[0]) if r else []
    except Exception:                                                   # noqa: BLE001
        return []


def near(con, g, p, max_jumps=12):
    """-> [(jumps, staging system, state, influence, has_boss, security of the staging system)] nearest first (only systems the universe map knows)."""
    out = []
    try:
        reach = g.reach(g.id_of(p.current_system), max_jumps, False)
    except Exception:                                                   # noqa: BLE001
        return out
    for i in _load(con):
        sid = i.get("staging_solar_system_id")
        if sid in reach:
            out.append((reach[sid].jumps, g.name[sid], i.get("state", "?"), float(i.get("influence", 0.0)), bool(i.get("has_boss")), g.sec[sid]))
    return sorted(out)


def lines(con, g, p):
    rows = near(con, g, p)
    if not _load(con):
        return ""
    L = ["INCURSIONS (Sansha, from the game; fleet content for strong ships: not routed, modeled for later):"]
    if not rows:
        L.append("   none within 12 jumps of you")
    for j, name, state, infl, boss, sec in rows[:5]:
        L.append(f"   {j} jumps: staging {name} ({sec:.1f}), {state}, influence {infl:.0%}" + (", boss spawned" if boss else ""))
    return "\n".join(L)
