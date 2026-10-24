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


JUMPS_KEY = "jump_log"


def _reset_ts(now=None):
    """The last 11:00 UTC (the daily reset / downtime) as a unix time."""
    import calendar
    import time
    now = now or time.time()
    t = time.gmtime(now)
    reset = calendar.timegm((t.tm_year, t.tm_mon, t.tm_mday, 11, 0, 0))
    return reset if reset <= now else reset - 86400


def record_move(con, g, from_name, to_name, now=None):
    """A system change seen by `next` / `sync`: log how many jumps it was (route length), so the AIR 'Complete 3 Jumps' goal knows what you already flew."""
    import json
    import time
    if not from_name or not to_name or from_name == to_name:
        return 0
    try:
        r = g.route(g.id_of(from_name), g.id_of(to_name), 60, True)
        jumps = r.jumps if r else 1
    except Exception:                                                   # noqa: BLE001
        jumps = 1
    try:
        row = con.execute("SELECT value FROM meta WHERE key=?", (JUMPS_KEY,)).fetchone()
        log = json.loads(row[0]) if row else []
        log.append([now or time.time(), from_name, to_name, jumps])
        con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (JUMPS_KEY, json.dumps(log[-200:])))
        con.commit()
    except Exception:                                                   # noqa: BLE001
        pass
    return jumps


def jumps_today(con, now=None):
    """Jumps flown since the last daily reset (11:00 UTC), from what `next` / `sync` saw."""
    import json
    try:
        row = con.execute("SELECT value FROM meta WHERE key=?", (JUMPS_KEY,)).fetchone()
        log = json.loads(row[0]) if row else []
    except Exception:                                                   # noqa: BLE001
        return 0
    since = _reset_ts(now)
    return sum(int(x[3]) for x in log if x[0] >= since)


def reversal(con, fly_target, here, now=None):
    """Would flying to `fly_target` take you straight back to where you just came from? -> 0 (no), 1 (a first reversal), 2 (the moves already went back and forth:
    A>B, B>A, A>B...). Used to stop the planner from ping-ponging between two systems."""
    import json
    import time
    try:
        row = con.execute("SELECT value FROM meta WHERE key=?", (JUMPS_KEY,)).fetchone()
        log = json.loads(row[0]) if row else []
    except Exception:                                                   # noqa: BLE001
        return 0
    now = now or time.time()
    log = [x for x in log if now - x[0] < 3 * 3600]
    try:                                         # the last FLY step `next` itself gave (A -> B): standing in B and told to go back to A is a reversal even if no move was logged
        lf = con.execute("SELECT value FROM meta WHERE key='last_fly'").fetchone()
        lf = json.loads(lf[0]) if lf else None
        if lf and now - lf[0] < 3 * 3600 and str(lf[1]).lower() == str(fly_target).lower() and str(lf[2]).lower() == str(here).lower():
            return 2 if (log and log[-1][1] == log[-1][2] or len(log) >= 2) else 1
    except Exception:                                                   # noqa: BLE001
        pass
    if not log or not fly_target or str(log[-1][1]).lower() != str(fly_target).lower() or str(log[-1][2]).lower() != str(here).lower():
        return 0
    if len(log) >= 2 and log[-2][1] == log[-1][2] and log[-2][2] == log[-1][1]:
        return 2
    return 1


REVISIT_MOVES = 6
REVISIT_HOURS = 3.0


def recent_systems(con, here, now=None, moves=REVISIT_MOVES, hours=REVISIT_HOURS):
    """Systems you passed through in your last `moves` moves (within `hours`), except where you are now. A plan that flies you back INTO one
    of them is a loop (2026-10-24: Uedama > Sivala > ... > Kamio > Halaima > Huttaken > Halaima > Kamio > Ikao > Uedama for ~0 ISK)."""
    import json
    import time
    try:
        row = con.execute("SELECT value FROM meta WHERE key=?", (JUMPS_KEY,)).fetchone()
        log = json.loads(row[0]) if row else []
    except Exception:                                                   # noqa: BLE001
        return set()
    now = now or time.time()
    log = [x for x in log if now - x[0] < hours * 3600][-moves:]
    out = {str(x[1]).lower() for x in log} | {str(x[2]).lower() for x in log}
    out.discard(str(here).lower())
    return out


def note_fly(con, here, target, now=None):
    """Remember the FLY step just given (here -> target) so the next call can tell a reversal."""
    import json
    import time
    try:
        con.execute("INSERT OR REPLACE INTO meta VALUES('last_fly', ?)", (json.dumps([now or time.time(), here, target]),))
        con.commit()
    except Exception:                                                   # noqa: BLE001
        pass
