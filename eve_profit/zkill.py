"""Hauler-loss map from zKillboard: where industrials/freighters/blockade runners/etc. were destroyed in the last 7 days.
zKillboard lists only killmail ids+hashes+values; CCP's killmail endpoint (public, immutable) gives the system and ship.
Be polite: identifying User-Agent, ~1 request/second, capped lookups per refresh. Written without network access in the
dev sandbox; verify with `python -m eve_profit zkill`."""
import gzip
import json
import time
import urllib.error
import urllib.request

from .config import USER_AGENT

BASE = "https://zkillboard.com/api"
# ship groups gankers target: Industrial, Freighter, Jump Freighter, Deep Space Transport, Blockade Runner,
# Industrial Command Ship, Mining Barge, Exhumer (ids from memory of the SDE: verify if results look empty)
HAULER_GROUPS = [28, 513, 902, 380, 1202, 941, 463, 543]
WINDOW_S = 7 * 86400          # zKillboard maximum
PAUSE_S = 1.1


class ZKill:
    def __init__(self, timeout=30, pause=PAUSE_S):
        self.timeout, self.pause, self._last = timeout, pause, 0.0

    def get(self, path):
        wait = self.pause - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        url = f"{BASE}/{path.strip('/')}/"
        for attempt in range(4):
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    raw = r.read()
                    if r.headers.get("Content-Encoding") == "gzip":
                        raw = gzip.decompress(raw)
                    self._last = time.time()
                    return json.loads(raw or b"[]")
            except urllib.error.HTTPError as e:
                if e.code in (429, 502, 503, 504):
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise
            except (TimeoutError, ConnectionError, urllib.error.URLError, json.JSONDecodeError):
                time.sleep(2 ** attempt)
        raise RuntimeError(f"zKillboard unreachable: {url}")


def refresh_gank_map(con, zk, esi, region_ids, max_lookups=150, per_region=200, log=print):
    """-> dict(listed, new, kept). Stores hauler losses (system, ship, value, time) for the last 7 days."""
    now = time.time()
    con.execute("DELETE FROM gank_events WHERE time < ?", (now - WINDOW_S - 3600,))
    known = {r[0] for r in con.execute("SELECT killmail_id FROM gank_events")}
    listed = new = 0
    groups = ",".join(map(str, HAULER_GROUPS))
    for rid in region_ids:
        log(f"  zKillboard: hauler losses in region {rid}...")
        rows = zk.get(f"losses/groupID/{groups}/regionID/{rid}/pastSeconds/{WINDOW_S}")[:per_region]
        listed += len(rows)
        for k in rows:
            kid, h = k.get("killmail_id"), (k.get("zkb") or {}).get("hash")
            if not kid or not h or kid in known or new >= max_lookups:
                continue
            try:
                km = esi.get(f"/killmails/{kid}/{h}/")[0]
            except Exception:
                continue
            con.execute("INSERT OR REPLACE INTO gank_events VALUES(?,?,?,?,?,?)",
                        (kid, km["solar_system_id"], km["victim"].get("ship_type_id", 0),
                         (k.get("zkb") or {}).get("totalValue", 0), km.get("killmail_time", ""), rid))
            known.add(kid)
            new += 1
    con.commit()
    return {"listed": listed, "new": new, "kept": con.execute("SELECT COUNT(*) FROM gank_events").fetchone()[0]}
