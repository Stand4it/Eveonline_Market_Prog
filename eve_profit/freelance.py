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


def detail_sample(con, pattern, n=4, width=2200):
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


KEYWORDS = re.compile(r"mine|mining|ore|deliver|compressed|veldspar|scordite|plagioclase|pyroxeres|omber|kernite|jaspet|hemorphite|hedbergite|crokite|gneiss|ochre|spodumain|bistot|arkonor|mercoxit|ice|insurance|replacement|haul|courier|buy ?back", re.I)


def alive(j):
    """A job that can still be worked: Active with ISK left (the list also holds old, used-up jobs)."""
    return j.get("state") == "Active" and (j.get("reward") or {}).get("remaining", 0) > 0 and (j.get("progress") or {}).get("desired", 0) > 0


def fetch_details(con, max_n=150, log=print):
    """Details (rules, broadcast systems) for the jobs that look like mining / delivery / insurance and have none yet, best pay per unit first. -> number fetched."""
    todo = [j for j in jobs(con) if alive(j) and KEYWORDS.search(j.get("name", "")) and per_unit(j) < 50000
            and not con.execute("SELECT 1 FROM freelance_raw WHERE job_id=? AND detail IS NOT NULL", (j["id"],)).fetchone()]
    todo.sort(key=lambda j: -(j.get("reward") or {}).get("remaining", 0))
    n = 0
    for j in todo[:max_n]:
        try:
            d = _get(f"/freelance-jobs/{j['id']}")
            con.execute("UPDATE freelance_raw SET detail=? WHERE job_id=?", (json.dumps(d, ensure_ascii=False), j["id"]))
            n += 1
            time.sleep(0.15)
        except Exception as e:                                          # noqa: BLE001
            log(f"   detail {j['id']} failed: {e}")
    con.commit()
    return n


def parse(lst, det):
    """One job -> a flat dict (method, pay per unit, per-person cap, items, destinations, broadcast systems, expiry). Unknown shapes give empty fields."""
    cfg, con_ = (det.get("configuration") or {}), (det.get("contribution") or {})
    par = cfg.get("parameters") or {}
    out = {"id": lst["id"], "name": lst.get("name", ""), "method": cfg.get("method", ""), "per_unit": con_.get("reward_per_contribution") or per_unit(lst),
           "cap_pp": con_.get("contribution_per_participant_limit"), "remaining_isk": (lst.get("reward") or {}).get("remaining", 0),
           "expires": (det.get("details") or {}).get("expires", ""), "corp": (((det.get("details") or {}).get("creator") or {}).get("corporation") or {}).get("name", ""),
           "broadcast": [(b["id"], b.get("name", "")) for b in (det.get("access_and_visibility") or {}).get("broadcast_locations", [])],
           "max_age_days": ((det.get("access_and_visibility") or {}).get("restrictions") or {}).get("maximum_age"), "items": [], "dest": []}
    ore = (par.get("ore") or {}).get("matcher", {}).get("values", [])
    for v in ore:
        out["items"] += [(v["value_type"], int(x)) for x in v["values"]]
    deliv = (par.get("corporation_item_delivery") or {}).get("corporation_item_delivery") or {}
    for v in (deliv.get("item_type") or {}).get("values", []):
        out["items"] += [(v["value_type"], int(x)) for x in v["values"]]
    for v in (deliv.get("corporation_office_location") or {}).get("values", []):
        out["dest"] += [(v["value_type"], int(x)) for x in v["values"]]
    return out


def near(con, g, p, max_jumps=5):
    """Detailed, alive jobs shown within max_jumps of where you are (distance to the nearest broadcast system), as parsed dicts with a 'jumps' field."""
    try:
        reach = g.reach(g.id_of(p.current_system), max_jumps, p.avoid_yellow)
    except Exception:                                                   # noqa: BLE001
        return []
    out = []
    for r in con.execute("SELECT listing, detail FROM freelance_raw WHERE detail IS NOT NULL"):
        lst, det = json.loads(r[0]), json.loads(r[1])
        if not alive(lst) or str((det.get("details") or {}).get("expires", "9")) < time.strftime("%Y-%m-%dT%H:%M"):
            continue
        j = parse(lst, det)
        d = [reach[b[0]].jumps for b in j["broadcast"] if b[0] in reach]
        if d:
            j["jumps"] = min(d)
            out.append(j)
    return sorted(out, key=lambda j: (j["jumps"], -j["per_unit"]))


def item_names(con, items):
    """(value_type, id) pairs -> readable names (types / groups from the SDE tables)."""
    names = []
    for vt, i in items:
        try:
            if vt == "item_type":
                r = con.execute("SELECT name FROM types WHERE type_id=?", (i,)).fetchone()
            else:
                r = con.execute("SELECT GROUP_CONCAT(name, '/') FROM (SELECT name FROM types WHERE group_id=? LIMIT 6)", (i,)).fetchone()
            names.append((r[0] if r and r[0] else f"{vt} {i}"))
        except Exception:                                               # noqa: BLE001
            names.append(f"{vt} {i}")
    return names


def report(con, g, p, max_jumps=5, top=20):
    rows = near(con, g, p, max_jumps)
    if not rows:
        return "No detailed freelance jobs near you yet: run  python -m eve_profit grabs --all  (it fetches details for mining and delivery jobs, 150 per run)."
    L = [f"{'jumps':>5} {'ISK/unit':>9}  method        what (corporation)"]
    for j in rows[:top]:
        what = ", ".join(item_names(con, j["items"])[:2]) or j["name"][:40]
        L.append(f"{j['jumps']:>5} {j['per_unit']:>9,.2f}  {j['method']:<13} {what[:46]} ({j['corp'][:22]})" + (f"  max age {j['max_age_days']} d" if j["max_age_days"] else ""))
    return "\n".join(L)


def stats(con):
    """One line each: job states, how many are alive, look like mining/delivery, and already have their details."""
    from collections import Counter
    js = jobs(con)
    st = Counter(j.get("state", "?") for j in js)
    al = [j for j in js if alive(j)]
    kw = [j for j in al if KEYWORDS.search(j.get("name", "")) and per_unit(j) < 50000]
    det = con.execute("SELECT COUNT(*) FROM freelance_raw WHERE detail IS NOT NULL").fetchone()[0]
    return f"states {dict(st)}; alive {len(al)}; mining/delivery-like {len(kw)}; details stored {det}"
