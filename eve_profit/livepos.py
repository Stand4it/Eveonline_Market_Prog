"""Where you are RIGHT NOW: `next` asks ESI for the character's location before it plans, so the one-jump step is measured from the system you are really in
(the profile only knows the place of the last `sync`, which is stale as soon as you fly)."""
import os


def refresh(con, p, client_id):
    """Update p.current_system / current_location_id from ESI. -> the new system name, or None when it could not be read (then the profile stays as it was)."""
    if os.environ.get("EVE_NO_LIVE"):
        return None
    try:
        from . import sso
        from .esi import ESI
        esi = ESI()
        esi.token, cid = sso.get_token(client_id)
        loc = esi.get(f"/characters/{cid}/location/")[0]
        row = con.execute("SELECT name FROM systems WHERE system_id=?", (loc["solar_system_id"],)).fetchone()
        if not row:
            return None
        p.current_system = row[0]
        p.current_location_id = loc.get("station_id") or loc.get("structure_id") or 0
        return row[0]
    except Exception:                                                   # noqa: BLE001
        return None


def refresh_ship(con, p, client_id):
    """The ship you are flying RIGHT NOW (you may have boarded another one since the last sync): update p.ship_name / ship_type_id / cargo_m3 from ESI.
    -> (new ship name, old ship name) when it changed, else None (also None when ESI could not be read)."""
    if os.environ.get("EVE_NO_LIVE"):
        return None
    try:
        from . import sso
        from .character import CAPACITY_ATTR, _hull_cargo_bonus
        from .esi import ESI
        esi = ESI()
        esi.token, cid = sso.get_token(client_id)
        ship = esi.get(f"/characters/{cid}/ship/")[0]
        tid = ship["ship_type_id"]
        name = ship.get("ship_name") or p.ship_name
        if tid == p.ship_type_id and name == p.ship_name:
            return None
        cap = None
        r = con.execute("SELECT capacity FROM types WHERE type_id=?", (tid,)).fetchone()
        if r and r[0]:
            cap = float(r[0])
        else:
            cap = next((a["value"] for a in esi.type_info(tid).get("dogma_attributes", []) if a["attribute_id"] == CAPACITY_ATTR), None)
        skills = [{"skill_id": s[0], "trained_skill_level": s[1]} for s in con.execute("SELECT skill_id,level FROM character_skills")]
        old = p.ship_name
        p.ship_name, p.ship_type_id = name, tid
        if cap:
            p.cargo_m3 = cap * _hull_cargo_bonus(con, tid, skills)
        return name, old
    except Exception:                                                   # noqa: BLE001
        return None
