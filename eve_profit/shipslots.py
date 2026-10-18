"""How many tools a hull can carry: high slots, turret hardpoints, launcher hardpoints (and mid / low / rig for the tank). The slot counts come from the game's own
dogma data (ESI, read at `sync` for the ship you fly and every ship you own) and are cached in meta 'ship_slots'. A hull with a high slot can carry a gun, a mining
laser, a salvager or a probe launcher, and a hull with more slots carries several at the same time: that is what `tools.fit_plan` works out."""
import json

ATTR = {14: "high", 13: "mid", 12: "low", 1137: "rig", 101: "launcher", 102: "turret"}
KEY = "ship_slots"


def _load(con):
    try:
        r = con.execute("SELECT value FROM meta WHERE key=?", (KEY,)).fetchone()
        return json.loads(r[0]) if r else {}
    except Exception:                                                   # noqa: BLE001
        return {}


def get(con, type_id):
    """-> {high, mid, low, rig, launcher, turret} for a hull, or None when it was never read."""
    return _load(con).get(str(int(type_id))) if type_id else None


def remember(con, esi, type_id):
    """Read one hull's slots from ESI once and keep them. -> the slots dict or None."""
    have = get(con, type_id)
    if have:
        return have
    try:
        attrs = esi.type_info(type_id).get("dogma_attributes", [])
    except Exception:                                                   # noqa: BLE001
        return None
    slots = {ATTR[a["attribute_id"]]: int(a["value"]) for a in attrs if a["attribute_id"] in ATTR}
    if "high" not in slots:
        return None
    d = _load(con)
    d[str(int(type_id))] = slots
    try:
        con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (KEY, json.dumps(d)))
    except Exception:                                                   # noqa: BLE001
        return None
    return slots


def owned_hulls(con, p):
    """[(name, system id or None, slots or None)] for the ship you fly (system None) and every ship you own."""
    out = []
    try:
        name = (getattr(p, "ship_name", "") or "").split(" - ")[0]
        if name and getattr(p, "ship_type_id", 0):
            out.append((name, None, get(con, p.ship_type_id)))
    except Exception:                                                   # noqa: BLE001
        pass
    try:
        for tid, sid, nm in con.execute("SELECT m.type_id, m.system_id, t.name FROM my_ships m JOIN types t ON t.type_id=m.type_id"):
            out.append((nm, sid, get(con, tid)))
    except Exception:                                                   # noqa: BLE001
        pass
    return out
