"""Wrecks to salvage, found automatically (owner 2026-10-24). ESI cannot see objects in space, but every destroyed ship leaves a wreck for ~2 hours:
ESI's hourly system_kills says WHERE ships died, the public zKillboard API lists each kill (ship, time). For systems near you with recent ship
kills, the kills of the last 2 hours become a salvage lead (data/kill_leads.json) that `next` ranks like any other option (leads.py: unknown =
your best ISK/hr until you time a salvage run; travel and the wreck's remaining life are counted; a lead that has expired drops out).
Salvaging another pilot's wreck is allowed and does not flag you; LOOTING it does (the loot value is shown, not counted).
python -m eve_profit.killleads            refresh now and print the leads"""
import json
import os
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "kill_leads.json")
UA = "eve_profit (personal EVE Online helper; contact via the EVE character Stand4it Dahl)"
WRECK_H = 2.0
MAX_SYSTEMS = 5
MAX_JUMPS = 4
CAPSULES = {670, 33328}                                                 # pods leave nothing worth salvaging
SALVAGE_PER_LEVEL = 5.0                                                 # Salvager I: 5% x Salvaging level (scripts/build_wreck_map.py)
DIFF_FILE = os.path.join(ROOT, "data", "wreck_difficulty.json")
SHIP_CATEGORY = 6                                                       # owner 2026-10-29: Mobile Depots etc. are not ship wrecks; only ships count
_WHERE = {}


def _where(con, loc_id):
    """zKillboard's nearest celestial for a kill -> 'Stargate (Tunttaras)', 'Ikuchi IV - Moon 2' ... ('' when unknown)."""
    if not loc_id:
        return ""
    if loc_id in _WHERE:
        return _WHERE[loc_id]
    nm = ""
    r = con.execute("SELECT name FROM stations WHERE station_id=?", (loc_id,)).fetchone()
    if r:
        nm = r[0]
    else:
        kinds = ["stargates"] if 50000000 <= loc_id < 60000000 else ["planets", "moons", "asteroid_belts", "stars"] if 40000000 <= loc_id < 50000000 else []
        for kind in kinds:
            try:
                nm = _get(f"https://esi.evetech.net/latest/universe/{kind}/{loc_id}/").get("name", "")
                break
            except Exception:                                           # noqa: BLE001
                continue
    _WHERE[loc_id] = nm
    return nm


def _get(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _salvaging(con):
    try:
        r = con.execute("SELECT level FROM character_skills WHERE skill_id=25863").fetchone()
        return int(r[0]) if r else 0
    except Exception:                                                   # noqa: BLE001
        return 0


def chance(diffs, ship_type, level):
    """owner 2026-10-29: % chance per salvager cycle for this ship's wreck at your Salvaging level; <= 0 = the game refuses ('not enough skill'); None = unknown hull."""
    d = diffs.get(str(ship_type))
    return None if d is None else d + SALVAGE_PER_LEVEL * level


def refresh(con, g, p, now=None, max_systems=MAX_SYSTEMS, max_jumps=MAX_JUMPS):
    """-> list of leads written to data/kill_leads.json (sync: max_jumps=0 = only the system you are in, always checked)."""
    now = now or time.time()
    try:
        here = g.id_of(p.current_system)
        reach = g.reach(here, max_jumps, p.avoid_yellow) if max_jumps else {here: type("R", (), {"jumps": 0})()}
        hot = con.execute("SELECT system_id, ship_kills FROM system_kills WHERE ship_kills>0").fetchall()
    except Exception:                                                   # noqa: BLE001
        return []
    hot = dict(hot)
    hot.setdefault(here, 1)                                             # the system you are in is always checked (kills of the last hour may not be counted yet)
    cand = sorted(((reach[s].jumps, -k, s) for s, k in hot.items() if s in reach), key=lambda x: (x[0], x[1]))[:max_systems]
    try:                                                                # keep other systems' leads from the last full refresh when only checking here
        old = [ld for ld in json.load(open(OUT, encoding="utf-8")).get("leads", [])
               if now <= ld["seen"] + ld.get("life_h", WRECK_H) * 3600 and g.id_of(ld["system"]) not in {c[2] for c in cand}]
    except Exception:                                                   # noqa: BLE001
        old = []
    leads = []
    try:
        diffs = json.load(open(DIFF_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        diffs = {}
    lvl = _salvaging(con)
    for _j, _k, sid in cand:
        try:
            kills = _get(f"https://zkillboard.com/api/kills/systemID/{sid}/pastSeconds/{int(WRECK_H * 3600)}/")
        except Exception:                                               # noqa: BLE001
            continue
        wrecks, newest, loot, ships, near, refused = 0, 0.0, 0.0, {}, {}, {}
        for k in (kills or [])[:30]:
            z = k.get("zkb", {})
            try:
                km = _get(f"https://esi.evetech.net/latest/killmails/{k['killmail_id']}/{z['hash']}/")
            except Exception:                                           # noqa: BLE001
                continue
            st = km.get("victim", {}).get("ship_type_id")
            cat = con.execute("SELECT category_id FROM types WHERE type_id=?", (st,)).fetchone()
            if st in CAPSULES or (cat and cat[0] is not None and cat[0] != SHIP_CATEGORY):
                continue
            t = time.mktime(time.strptime(km["killmail_time"], "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
            if now - t > WRECK_H * 3600:
                continue
            r = con.execute("SELECT name FROM types WHERE type_id=?", (st,)).fetchone()
            nm = r[0] if r else str(st)
            c = chance(diffs, st, lvl)
            if c is not None and c <= 0:
                refused[nm] = refused.get(nm, 0) + 1                    # the game would say you lack the skill: not counted, not sent
                continue
            wrecks += 1
            newest = max(newest, t)
            loot += float(z.get("droppedValue") or 0)
            tag = f"{nm} ({c:.0f}%)" if c is not None else f"{nm} (chance unknown: try it)"
            ships[tag] = ships.get(tag, 0) + 1
            w = _where(con, z.get("locationID")) or "unknown spot (look in Overview: Wrecks, or warp around)"
            near[w] = near.get(w, 0) + 1
        if not wrecks:
            continue
        what = ", ".join(f"{n} x {s}" for s, n in sorted(ships.items(), key=lambda x: -x[1])[:5])
        spots = sorted(near.items(), key=lambda x: -x[1])
        where = "; ".join(f"{n} near {w}" for w, n in spots)
        go = spots[0][0]
        dest = (f" Set destination: python scripts/set_dest.py \"{go}\" (autopilot warps you there), or" if con.execute("SELECT 1 FROM stations WHERE name=?", (go,)).fetchone() else "")
        skip = ("; NOT counted (your Salvaging " + str(lvl) + " is too low, the game refuses them): " + ", ".join(f"{n} x {s}" for s, n in refused.items())) if refused else ""
        leads.append({"id": f"kills-{sid}-{int(newest)}", "system": g.name[sid], "activity": "salvaging", "needs": "salvager",
                      "seen": int(newest), "life_h": WRECK_H, "count": wrecks, "auto": "zkillboard", "where": where, "go": go,
                      "what": f"{wrecks} wreck(s) you can salvage (chance per cycle at Salvaging {lvl}) from the last {WRECK_H:.0f} h ({what}){skip}; salvage only (looting another pilot's wreck flags you); "
                              f"dropped loot ~{loot:,.0f} ISK is NOT counted. WHERE: {where}. GO:{dest} right-click space (or Overview) > {go} > Warp to Within 0 m, then Overview: Wrecks. If the game still refuses, stopsync with nothing gained: your timed run then sets the real rate"})
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({"refreshed": now, "leads": old + leads}, open(OUT, "w", encoding="utf-8"), indent=1)
    return old + leads


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ROOT)
    from eve_profit.config import Profile
    from eve_profit.db import connect
    from eve_profit.graph import Graph
    con = connect(os.environ.get("EVE_PROFIT_DB") or "E:/EveProfit/eve_profit_dahl.db")
    p = Profile.load(os.path.join(ROOT, "profile_dahl.json"))
    L = refresh(con, Graph(con), p)
    print(f"{len(L)} wreck lead(s) within {MAX_JUMPS} jumps of {p.current_system}:")
    for ld in L:
        print(f"   {ld['system']}: {ld['what']}")
