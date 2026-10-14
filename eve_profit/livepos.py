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
