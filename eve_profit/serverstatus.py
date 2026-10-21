"""CCP's public status page (status.eveonline.com, a Statuspage JSON feed): is ESI / the game server up, and any maintenance or incident.
Used when ESI keeps failing, so the message says WHY (planned maintenance, extended downtime) instead of only '503'."""
import json
import urllib.request

URL = "https://status.eveonline.com/api/v2/summary.json"
WATCH = ("EVE Swagger Interface (ESI)", "Game Server", "Tranquility", "Login")


def summary(timeout=8):
    """-> list of short lines, [] when the page cannot be read."""
    try:
        req = urllib.request.Request(URL, headers={"User-Agent": "eve_profit status check"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            s = json.load(r)
    except Exception:                                                   # noqa: BLE001
        return []
    L = [f"EVE server status: {s.get('status', {}).get('description', '?')}"]
    comp = {c.get("name"): c.get("status", "?") for c in s.get("components", [])}
    bad = [f"{n}: {comp[n].replace('_', ' ')}" for n in WATCH if n in comp and comp[n] != "operational"]
    if bad:
        L.append("   " + "; ".join(bad))
    for m in s.get("scheduled_maintenances", []):
        L.append(f"   maintenance: {m.get('name')} ({m.get('status')}) {m.get('scheduled_for', '')[:16]} -> {m.get('scheduled_until', '')[:16]} UTC")
    for i in s.get("incidents", []):
        L.append(f"   incident: {i.get('name')} ({i.get('status')})")
    L.append("   details: https://status.eveonline.com")
    return L


if __name__ == "__main__":
    print("\n".join(summary() or ["status page not reachable"]))
