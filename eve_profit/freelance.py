"""Freelance Jobs straight from ESI (public routes GET /freelance-jobs and GET /freelance-jobs/{job_id}; found with `esiroutes`).
The raw answers are stored in the database (table freelance_raw) so nothing is lost, and the first run prints a short sample so the field names can be mapped."""
import json
import time
import urllib.request

BASES = ("https://esi.evetech.net", "https://esi.evetech.net/latest")
HEADERS = {"User-Agent": "eve_profit freelance reader", "Accept": "application/json", "X-Compatibility-Date": "2025-12-16"}


def _get(path, params=""):
    err = ""
    for b in BASES:
        try:
            req = urllib.request.Request(b + path + params, headers=HEADERS)
            r = urllib.request.urlopen(req, timeout=40)
            return json.load(r), int(r.headers.get("X-Pages", 1) or 1)
        except Exception as e:                                          # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
    raise RuntimeError(err)


def fetch(con, details=True, log=print, cap=300, reuse_h=24.0):
    """Download the list (all pages) and, for each job, its detail. -> (jobs, details stored)."""
    con.execute("CREATE TABLE IF NOT EXISTS freelance_raw(job_id TEXT PRIMARY KEY, fetched REAL, listing TEXT, detail TEXT)")
    first, pages = _get("/freelance-jobs")
    rows = list(first if isinstance(first, list) else first.get("jobs", first.get("items", [first])))
    for pg in range(2, pages + 1):
        more, _ = _get("/freelance-jobs", f"?page={pg}")
        rows += list(more if isinstance(more, list) else more.get("jobs", more.get("items", [])))
    now, n_det = time.time(), 0
    have = {r[0]: r[1] for r in con.execute("SELECT job_id,fetched FROM freelance_raw WHERE detail IS NOT NULL")}
    for r in rows[:cap]:
        jid = str(r.get("job_id", r.get("id", r)) if isinstance(r, dict) else r)
        det = None
        if details and jid in have and now - have[jid] < reuse_h * 3600.0:      # a detail fetched recently is kept: only new jobs cost a call
            con.execute("UPDATE freelance_raw SET listing=? WHERE job_id=?", (json.dumps(r, ensure_ascii=False), jid))
            continue
        if details:
            try:
                det, _ = _get(f"/freelance-jobs/{jid}")
                n_det += 1
                time.sleep(0.15)
            except Exception as e:                                      # noqa: BLE001
                log(f"   detail {jid} failed: {e}")
        con.execute("INSERT OR REPLACE INTO freelance_raw VALUES(?,?,?,?)", (jid, now, json.dumps(r, ensure_ascii=False), json.dumps(det, ensure_ascii=False) if det is not None else None))
    con.commit()
    return len(rows), n_det


def sample(con, n=2, width=900):
    out = []
    for r in con.execute("SELECT job_id, listing, detail FROM freelance_raw ORDER BY job_id LIMIT ?", (n,)):
        out.append(f"--- job {r[0]}\nlisting: {r[1][:width]}\ndetail:  {(r[2] or '')[:width]}")
    return "\n".join(out)
