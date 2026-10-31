"""Minimal ESI client (public endpoints, no auth). Stdlib only, honours ETag/Expires.
NOTE: written without network access in the dev sandbox; verify with `scripts\\check_esi`."""
import http.client
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import USER_AGENT

BASE = "https://esi.evetech.net/latest"


DOWN_S = 300          # after a call fails all its retries on 5xx/420, later calls in this run get ONE try for this long
_DOWN_UNTIL = 0.0


class ESI:
    def __init__(self, timeout=20):
        self.timeout, self.etags, self.cache = timeout, {}, {}

    token = None  # bearer access token for authenticated endpoints (set by sso)

    def get(self, path, **params):
        """-> (json, pages). Retries on 420/5xx; uses ETag for cheap refreshes."""
        global _DOWN_UNTIL
        url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
        tries = 1 if time.time() < _DOWN_UNTIL else 5            # ESI already failed this run: one quick try, no 31 s of back-off per call
        busy = None
        for attempt in range(tries):
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                       "Accept": "application/json"})
            if self.token:
                req.add_header("Authorization", "Bearer " + self.token)
            if url in self.etags:
                req.add_header("If-None-Match", self.etags[url])
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    data = json.load(r)
                    pages = int(r.headers.get("X-Pages", 1))
                    if r.headers.get("ETag"):
                        self.etags[url] = r.headers["ETag"]
                        self.cache[url] = (data, pages)
                    if int(r.headers.get("X-ESI-Error-Limit-Remain", 100)) < 20:
                        time.sleep(5)
                    return data, pages
            except urllib.error.HTTPError as e:
                if e.code == 304 and url in self.cache:
                    return self.cache[url]
                if e.code in (420, 429, 500, 502, 503, 504):
                    busy = e.code
                    if attempt + 1 < tries:
                        print(f"  ESI answered {e.code} (busy/limited); retrying in {2 ** attempt}s...", flush=True)
                        time.sleep(2 ** attempt)
                    continue
                raise
            except (socket.timeout, TimeoutError, ConnectionError, http.client.IncompleteRead,
                    json.JSONDecodeError, urllib.error.URLError) as e:
                wait = min(2 ** attempt, 20)
                print(f"  network stall/error ({type(e).__name__}); retry {attempt + 1}/5 in {wait}s...", flush=True)
                time.sleep(wait)
                continue
        if busy and time.time() >= _DOWN_UNTIL:
            _DOWN_UNTIL = time.time() + DOWN_S
            print(f"  ESI keeps answering {busy}: CCP's server is busy or down. For the next {DOWN_S // 60} min this run tries each call once and uses saved data.", flush=True)
            try:
                from .serverstatus import summary
                for ln in summary():
                    print("  " + ln, flush=True)
            except Exception:                                           # noqa: BLE001
                pass
        raise RuntimeError(f"ESI failed: {url}")

    def region_orders(self, region_id, max_pages=None, log=None):
        out, page, pages = [], 1, 1
        while page <= pages and (max_pages is None or page <= max_pages):
            data, pages = self.get(f"/markets/{region_id}/orders/", order_type="all", page=page)
            out.extend(data)
            if log and (page == 1 or page % 25 == 0 or page == pages):
                log(f"  region {region_id}: page {page}/{pages} ({len(out):,} orders)")
            page += 1
        return out

    def system_kills(self):
        return self.get("/universe/system_kills/")[0]

    def type_info(self, type_id):
        return self.get(f"/universe/types/{type_id}/")[0]

    def paged(self, path, **params):
        out, page, pages = [], 1, 1
        while page <= pages:
            data, pages = self.get(path, page=page, **params)
            out.extend(data)
            page += 1
        return out

    def status(self):
        return self.get("/status/")[0]


def region_age_min(con, rid):
    """Minutes since this region's orders were last downloaded (None = never)."""
    t = con.execute("SELECT MAX(fetched_at) FROM orders WHERE region_id=?", (rid,)).fetchone()[0]
    return None if t is None else (time.time() - t) / 60.0


def refresh_orders(con, esi, region_ids, max_pages=None, max_age=0, budget_min=0):
    """Replace order book for the given regions + update kill counts + missing types.
    max_age (minutes): skip regions downloaded more recently than that. Each region is saved as soon as it
    arrives, so Ctrl+C keeps everything downloaded so far."""
    now = time.time()
    n = 0
    for rid in region_ids:
        if budget_min and (time.time() - now) / 60.0 > budget_min:
            print(f"  time budget of {budget_min:g} min reached: the remaining regions keep their older data (run scan --live again for them)", flush=True)
            break
        age = region_age_min(con, rid)
        if max_age and age is not None and age < max_age:
            print(f"  region {rid}: already fresh ({age:.0f} min old), skipped", flush=True)
            continue
        rows = esi.region_orders(rid, max_pages, log=lambda m: print(m, flush=True))
        vals = [(o["order_id"], o["type_id"], o["location_id"], o["system_id"], rid, int(o["is_buy_order"]), o["price"], o["volume_remain"],
                 o.get("min_volume", 1), o.get("issued", ""), now) for o in rows]
        if con.isolation_level is None:                                 # autocommit scan (owner 2026-10-29: The Forge's swap held the lock > 2 min and `next` failed):
            con.execute("CREATE TEMP TABLE IF NOT EXISTS orders_stage AS SELECT * FROM orders WHERE 0")
            con.execute("DELETE FROM orders_stage")                     # stage the rows in the temp database first (no lock on the main file)
            con.executemany("INSERT INTO orders_stage VALUES(?,?,?,?,?,?,?,?,?,?,?)", vals)
            con.execute("BEGIN IMMEDIATE")                              # then the swap itself is one short copy
            con.execute("DELETE FROM orders WHERE region_id=?", (rid,))
            con.execute("INSERT OR REPLACE INTO orders SELECT * FROM orders_stage")
        else:
            con.execute("DELETE FROM orders WHERE region_id=?", (rid,))
            con.executemany("INSERT OR REPLACE INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?)", vals)
        from .orders import bump as _bump
        _bump(con)                                                      # cached order books are stale now
        try:
            from .remoterange import store as _store_range
            _store_range(con, rows)                                     # a buy order's range: how far away a seller may be
        except Exception:                                               # noqa: BLE001
            pass
        con.commit()
        n += len(rows)
    con.execute("DELETE FROM system_kills")
    con.executemany("INSERT INTO system_kills VALUES(?,?,?,?)",
                    [(k["system_id"], k["ship_kills"], k["pod_kills"], now)
                     for k in esi.system_kills()])
    con.execute("DELETE FROM prices")
    con.executemany("INSERT OR IGNORE INTO prices VALUES(?,?)",
                    [(x["type_id"], x.get("adjusted_price", 0)) for x in esi.get("/markets/prices/")[0]])
    missing = [r[0] for r in con.execute(
        "SELECT DISTINCT type_id FROM orders WHERE type_id NOT IN (SELECT type_id FROM types)")]
    for tid in missing[:300]:  # cap per pass; remaining fill in on later scans
        t = esi.type_info(tid)
        con.execute("INSERT OR REPLACE INTO types(type_id,name,volume,group_id) VALUES(?,?,?,?)",
                    (tid, t.get("name"), t.get("packaged_volume", t.get("volume", 1)),
                     t.get("group_id")))
    con.commit()
    return n


def _post(self, path, token, **params):
    """Authenticated POST with query params, empty body. -> HTTP status."""
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, data=b"", method="POST", headers={
        "User-Agent": USER_AGENT, "Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=self.timeout) as r:
        return r.status


ESI.post = lambda self, path, **params: _post(self, path, self.token, **params)


def _post_json(self, path, body):
    import json as _json
    req = urllib.request.Request(BASE + path, data=_json.dumps(body).encode(), method="POST", headers={
        "User-Agent": USER_AGENT, "Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=self.timeout) as r:
        return _json.load(r)


ESI.post_json = _post_json


def refresh_item(con, esi, region_ids, type_id):
    """Fresh public orders for ONE item in the given regions (a handful of calls, not a full download).
    Replaces that item's NPC-station orders in those regions; structure orders are left alone."""
    now, n = time.time(), 0
    for rid in region_ids:
        rows = esi.paged(f"/markets/{rid}/orders/", order_type="all", type_id=type_id)
        con.execute("DELETE FROM orders WHERE region_id=? AND type_id=? AND location_id<1000000000000", (rid, type_id))
        con.executemany(
            "INSERT OR REPLACE INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [(o["order_id"], o["type_id"], o["location_id"], o["system_id"], rid, int(o["is_buy_order"]),
              o["price"], o["volume_remain"], o.get("min_volume", 1), o.get("issued", ""), now) for o in rows])
        from .orders import refresh_type as _refresh_type
        _refresh_type(con, type_id)                                     # only this item's cached books are stale
        try:
            from .remoterange import store as _store_range
            _store_range(con, rows)
        except Exception:                                               # noqa: BLE001
            pass
        n += len(rows)
    con.commit()
    return n
