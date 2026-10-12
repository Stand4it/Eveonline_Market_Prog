"""Freelance Jobs straight from ESI (public routes GET /freelance-jobs and GET /freelance-jobs/{id}; found with `esiroutes`).
Answer shape (seen 2026-10-12): {"cursor": {"before","after"}, "freelance_jobs": [{"id","name","state","last_modified","progress":{"current","desired"},
"reward":{"initial","remaining"}}]}, 10 jobs per page, pages follow the cursor. Reward per unit = reward.initial / progress.desired (Veldspar mining job: 1,250,000,000 / 250,000,000 = 5.00)."""
import json
import re
import time
import urllib.parse
import urllib.request

BASES = ("https://esi.evetech.net", "https://esi.evetech.net/latest")
HEADERS = {"User-Agent": "eve_profit freelance reader", "Accept": "application/json", "X-Compatibility-Date": "2025-12-16"}
LAST = {}
MAX_PAGES = 60


def _get(path, params=None):
    err = ""
    q = ("?" + urllib.parse.urlencode(params)) if params else ""
    for b in BASES:
        try:
            req = urllib.request.Request(b + path + q, headers=HEADERS)
            r = urllib.request.urlopen(req, timeout=40)
            LAST["expires"] = r.headers.get("Expires")                  # when ESI's own cache of this answer ends
            return json.load(r)
        except Exception as e:                                          # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
    raise RuntimeError(err)


def _all_jobs():
    """Every job: ask for a big page first (params after/before/limit), then follow the cursor in both directions until nothing new comes. -> list of job dicts."""
    jobs, seen = [], set()
    d, limit = None, 0
    for lim in (1000, 200, 100, 50, 0):
        try:
            d, limit = _get("/freelance-jobs", {"limit": lim} if lim else None), lim
            break
        except RuntimeError:
            continue
    if d is None:
        raise RuntimeError("freelance list not reachable")
    for _ in range(MAX_PAGES):
        page = d.get("freelance_jobs", []) if isinstance(d, dict) else list(d)
        fresh = [j for j in page if j["id"] not in seen]
        jobs += fresh
        seen.update(j["id"] for j in fresh)
        cur = (d.get("cursor") or {}) if isinstance(d, dict) else {}
        nxt = None
        for key in ("before", "after"):                                  # older first, then newer: whichever still brings new jobs
            if cur.get(key):
                try:
                    d2 = _get("/freelance-jobs", {key: cur[key], **({"limit": limit} if limit else {})})
                except RuntimeError:
                    continue
                if [j for j in d2.get("freelance_jobs", []) if j["id"] not in seen]:
                    nxt = d2
                    break
        if nxt is None:
            break
        d = nxt
    return jobs


def per_unit(j):
    des = (j.get("progress") or {}).get("desired") or 0
    return (j.get("reward") or {}).get("initial", 0) / des if des else 0.0


def fetch(con, details=False, log=print, cap=5000, reuse_h=24.0, only=None):
    """Download the whole list into freelance_raw (the listing row is the job itself); jobs that vanished are removed. -> (jobs, details stored)."""
    con.execute("CREATE TABLE IF NOT EXISTS freelance_raw(job_id TEXT PRIMARY KEY, fetched REAL, listing TEXT, detail TEXT)")
    jobs = _all_jobs()[:cap]
    now = time.time()
    before = {r[0] for r in con.execute("SELECT job_id FROM freelance_raw")}
    ids_now = {j["id"] for j in jobs}
    LAST["new"], LAST["gone"], LAST["total"] = (len(ids_now - before) if before else 0), len(before - ids_now), len(ids_now)
    con.executemany("DELETE FROM freelance_raw WHERE job_id=?", [(i,) for i in before - ids_now])      # taken, finished or withdrawn: no longer considered
    for j in jobs:
        old = con.execute("SELECT detail FROM freelance_raw WHERE job_id=?", (j["id"],)).fetchone()
        con.execute("INSERT OR REPLACE INTO freelance_raw VALUES(?,?,?,?)", (j["id"], now, json.dumps(j, ensure_ascii=False), old[0] if old else None))
    n_det = 0
    if details:
        for j in jobs:
            if only and not re.search(only, j.get("name", ""), re.I):
                continue                                                # details only for the jobs asked for (a call each)
            if con.execute("SELECT detail FROM freelance_raw WHERE job_id=? AND detail IS NOT NULL", (j["id"],)).fetchone():
                continue
            try:
                d = _get(f"/freelance-jobs/{j['id']}")
                con.execute("UPDATE freelance_raw SET detail=? WHERE job_id=?", (json.dumps(d, ensure_ascii=False), j["id"]))
                n_det += 1
                time.sleep(0.15)
            except Exception as e:                                      # noqa: BLE001
                log(f"   detail {j['id']} failed: {e}")
    con.commit()
    return len(jobs), n_det


def jobs(con):
    try:
        return [json.loads(r[0]) for r in con.execute("SELECT listing FROM freelance_raw")]
    except Exception:                                                   # noqa: BLE001
        return []


def mining_jobs(con):
    """The 'mining <ore>' jobs from the downloaded list: [{ore,title,isk_per_unit,cap_units,remaining_isk}] (cap per person assumed 1,000,000 units)."""
    out = []
    for j in jobs(con):
        m = re.search(r"mining (\w+)", j.get("name", ""), re.I)
        if m and j.get("state") == "Active" and per_unit(j) > 0 and "deliver" not in j["name"].lower():
            out.append({"ore": m.group(1).capitalize(), "title": j["name"], "isk_per_unit": per_unit(j), "cap_units": 1000000,
                        "remaining_isk": (j.get("reward") or {}).get("remaining", 0), "id": j["id"]})
    return out


def sample(con, n=3):
    rows = sorted(jobs(con), key=lambda j: -per_unit(j))[:n]
    return "\n".join(f"{j['name'][:48]:<48} {per_unit(j):>10,.2f} ISK per unit  {(j.get('progress') or {}).get('current', 0):,}/{(j.get('progress') or {}).get('desired', 0):,}" for j in rows)


def detail_sample(con, pattern, n=1, width=3500):
    """The detail of the first jobs matching the pattern WITHOUT the long description, so the rules (configuration) fit on screen."""
    out = []
    for r in con.execute("SELECT listing, detail FROM freelance_raw WHERE detail IS NOT NULL"):
        lst = json.loads(r[0])
        if re.search(pattern, lst.get("name", ""), re.I):
            d = json.loads(r[1])
            (d.get("details") or {}).pop("description", None)
            out.append(f"{lst.get('name')}\n" + json.dumps({k: v for k, v in d.items() if k not in ("id", "name")}, ensure_ascii=False)[:width])
            if len(out) >= n:
                break
    return "\n---\n".join(out)
