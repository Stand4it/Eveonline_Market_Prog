"""WHEN NOTHING WATCHES THE SCREEN: the hourly task and many steps run code inside `try/except` so one failure never stops the planner, which also hides the bug. `record` keeps every
swallowed error (where, message, file:line, count, last time) in errors.log next to the project and in the database; `check` reads errors.log and hourly.log for tracebacks and
'skipped' / 'failed' lines of the last 24 hours. `next` prints ONE line when something broke so a bug shows up the day it happens, not whenever a command is run by hand."""
import json
import os
import time

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ERR_FILE = os.path.join(_DIR, "errors.log")
HOURLY = os.path.join(_DIR, "hourly.log")
DAY = 24 * 3600.0


def record(where, exc):
    """Remember a swallowed exception. Never raises."""
    import sys
    if "unittest" in sys.modules:                                       # tests swallow errors on purpose
        return
    try:
        import traceback
        t = traceback.extract_tb(exc.__traceback__)[-1]
        line = {"t": time.time(), "where": where, "msg": f"{type(exc).__name__}: {exc}"[:200], "at": f"{os.path.basename(t.filename)}:{t.lineno} in {t.name}"}
        with open(ERR_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")
    except Exception:                                                   # noqa: BLE001
        pass


def recent(now=None):
    """-> {(where, msg, at): count} of the errors of the last 24 h."""
    now = now or time.time()
    out = {}
    try:
        with open(ERR_FILE, encoding="utf-8") as f:
            for ln in f:
                try:
                    d = json.loads(ln)
                except ValueError:
                    continue
                if now - d.get("t", 0) <= DAY:
                    k = (d["where"], d["msg"], d["at"])
                    out[k] = out.get(k, 0) + 1
    except OSError:
        pass
    return out


def log_problems(path=None, now=None):
    """Lines of the hourly log (modified in the last 24 h) that look like trouble: Traceback, ' skipped', ' failed', 'Error'."""
    now = now or time.time()
    path = path or HOURLY
    out = []
    try:
        if now - os.path.getmtime(path) > DAY:
            return out
        with open(path, encoding="utf-8", errors="replace") as f:
            for ln in f.readlines()[-4000:]:
                if any(w in ln for w in ("Traceback", "Error:", "skipped:", " failed", "disk I/O")):
                    out.append(ln.strip()[:160])
    except OSError:
        pass
    return out[-8:]


def line():
    """One line for `next` ('' when all is quiet)."""
    r, lp = recent(), log_problems()
    n = sum(r.values()) + len(lp)
    if not n:
        return ""
    return f"HEALTH: {n} problem(s) in the last 24 h (errors hidden inside steps or in the hourly log). Show them:  python -m eve_profit health"


def report():
    L = ["HEALTH (last 24 hours)"]
    r = recent()
    for (where, msg, at), n in sorted(r.items(), key=lambda kv: -kv[1])[:15]:
        L.append(f"   {n:>3} x {where}: {msg}  [{at}]")
    for ln in log_problems():
        L.append(f"   hourly.log: {ln}")
    if len(L) == 1:
        L.append("   all quiet: no swallowed errors and no trouble in hourly.log")
    return "\n".join(L)
