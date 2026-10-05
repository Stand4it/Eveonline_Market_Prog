"""Route automation via ESI waypoints (scope esi-ui.write_waypoint.v1).
ESI only sets waypoints in your open game client; YOU still press autopilot / fly.
Because the in-game router may choose its own (unsafe) path, we set a waypoint at EVERY
system on our safe path so the client cannot detour through red space."""
import time


def dedupe(wps):
    out = []
    for w in wps:
        if not out or out[-1] != w:
            out.append(w)
    return out


def dedupe_ids(ids):
    return dedupe(ids)


def route_alerts(g, waypoints):
    """Systems on the route that need attention: red (never go) or hot (recent kills)."""
    out = []
    for s in waypoints:
        n = getattr(g, "gank", {}).get(s, 0)
        if g.is_red(s):
            out.append((g.name[s], "RED"))
        elif n:
            out.append((g.name[s], f"GANKS x{n} in 7 days (haulers destroyed here)"))
        elif g.is_hot(s):
            out.append((g.name[s], "HOT"))
    return out


def send_route(esi, g, waypoints, send=False, pause=0.3, stops=None):
    """Dry-run by default. Refuses any route containing a red system."""
    wps = dedupe(waypoints)
    red = [g.name[s] for s in wps if g.is_red(s)]
    if red:
        raise ValueError("refusing route through red systems: " + ", ".join(red))
    dests = list(waypoints)
    pre = []
    for idx, loc in (stops or []):          # swap the system waypoint for the station in it so autopilot docks
        if idx < 0:
            pre.append(loc)
        elif idx < len(dests):
            dests[idx] = loc
    sent = pre + dedupe_ids(dests)
    if send:
        for i, sid in enumerate(sent):
            esi.post("/ui/autopilot/waypoint/", destination_id=sid,
                     add_to_beginning="false", clear_other_waypoints="true" if i == 0 else "false")
            time.sleep(pause)
    return [g.name[s] for s in wps]
