"""Lists seen on screen (Freelance Jobs ...): kept in the database (E:\\EveProfit\\...db with everything else) so each new screenshot is compared with the stored
list: NEW items, items that are GONE (taken, finished or withdrawn: dropped from consideration), and how fast the list changes (which sets how often
the screen is asked for). I read each screenshot and write a snapshot file under snapshots/<list>/ in the repo; the tool imports unseen snapshots when it runs.
Snapshot: {"list","ts","complete":true if the WHOLE list was visible,"items":[{"key","title",...}]}. Only a complete snapshot can mark items gone."""
import glob
import json
import os
import re
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WANTED_ID = {"freelance": "freelance_list"}          # list -> its entry in screens_wanted.json (its interval adapts to the change rate)


def key_of(title, kind):
    return re.sub(r"\W+", "_", title.lower()) + "|" + kind


def ensure(con):
    con.execute("CREATE TABLE IF NOT EXISTS listings(list_id TEXT, key TEXT, title TEXT, data TEXT, first_seen TEXT, last_seen TEXT, status TEXT, PRIMARY KEY(list_id,key))")
    con.execute("CREATE TABLE IF NOT EXISTS listing_history(list_id TEXT, ts TEXT, new INTEGER, gone INTEGER, total INTEGER)")


def _imported(con):
    r = con.execute("SELECT value FROM meta WHERE key='snap_imported'").fetchone()
    return set(json.loads(r[0])) if r else set()


def import_snapshots(con):
    """Apply every snapshot file not imported yet, oldest first. -> list of one-line summaries."""
    ensure(con)
    done, out = _imported(con), []
    for f in sorted(glob.glob(os.path.join(_ROOT, "snapshots", "*", "*.json"))):
        name = os.path.relpath(f, _ROOT).replace("\\", "/")
        if name in done:
            continue
        try:
            snap = json.load(open(f, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append(apply(con, snap))
        done.add(name)
    if out:
        con.execute("INSERT OR REPLACE INTO meta VALUES('snap_imported',?)", (json.dumps(sorted(done)),))
        con.commit()
    return out


def apply(con, snap):
    lst, ts, items = snap["list"], snap["ts"], snap["items"]
    old = {r[0]: r[1] for r in con.execute("SELECT key,status FROM listings WHERE list_id=?", (lst,))}
    seen, new = set(), 0
    for it in items:
        seen.add(it["key"])
        if it["key"] not in old:
            new += 1
            con.execute("INSERT INTO listings VALUES(?,?,?,?,?,?,'active')", (lst, it["key"], it["title"], json.dumps(it, ensure_ascii=False), ts, ts))
        else:
            con.execute("UPDATE listings SET data=?, last_seen=?, status='active' WHERE list_id=? AND key=?", (json.dumps(it, ensure_ascii=False), ts, lst, it["key"]))
    gone = 0
    if snap.get("complete"):
        for k, st in old.items():
            if st == "active" and k not in seen:
                gone += 1
                con.execute("UPDATE listings SET status='gone' WHERE list_id=? AND key=?", (lst, k))
    total = len(items)
    con.execute("INSERT INTO listing_history VALUES(?,?,?,?,?)", (lst, ts, new, gone, total))
    _adapt(con, lst, new if old else 0, gone, total)
    con.commit()
    return f"{lst} {ts}: {total} seen, {new} new, {gone} gone"


def _adapt(con, lst, new, gone, total):
    """The change rate sets how often the screen is asked for: lots of change -> twice as often (not below min_h), almost none -> 1.5x less often."""
    wid = WANTED_ID.get(lst)
    if not wid or not total:
        return
    try:
        item = next(i for i in json.load(open(os.path.join(_ROOT, "screens_wanted.json"), encoding="utf-8"))["items"] if i["id"] == wid)
        r = con.execute("SELECT value FROM meta WHERE key='wanted_state'").fetchone()
        st = json.loads(r[0]) if r else {}
        s = st.get(wid)
        if not s:
            return
        frac = (new + gone) / float(total)
        iv = s.get("int") or item.get("base_h", 12)
        if frac >= 0.2:
            iv = max(item.get("min_h", 6), iv / 2.0)
        elif frac < 0.05:
            iv = min(item.get("max_h", 168), iv * 1.5)
        s["int"] = iv
        con.execute("INSERT OR REPLACE INTO meta VALUES('wanted_state',?)", (json.dumps(st),))
    except Exception:                                                   # noqa: BLE001
        return


def is_gone(con, lst, key):
    try:
        r = con.execute("SELECT status FROM listings WHERE list_id=? AND key=?", (lst, key)).fetchone()
        return bool(r and r[0] == "gone")
    except Exception:                                                   # noqa: BLE001
        return False


def active(con, lst, kind=None):
    try:
        rows = [json.loads(r[0]) for r in con.execute("SELECT data FROM listings WHERE list_id=? AND status='active'", (lst,))]
    except Exception:                                                   # noqa: BLE001
        return []
    return [r for r in rows if not kind or r.get("kind") == kind]
