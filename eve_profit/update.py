"""`update`: has CCP published new game data (a patch)? New patches add items, blueprints, ships and skills, so after one
you should reload the universe/SDE and re-run `scan`, `bpbuy` and `skills`.
Checks developers.eveonline.com/static-data/tranquility/latest.jsonl (build number). Written without network access
in the dev sandbox: the parser is tolerant, and the stored value is just the raw first line."""
import json
import urllib.request

from .config import USER_AGENT
from .db import get_meta, set_meta

LATEST = "https://developers.eveonline.com/static-data/tranquility/latest.jsonl"


def fetch_latest(url=LATEST):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace").strip().splitlines()[0]


def build_of(line):
    try:
        d = json.loads(line)
    except json.JSONDecodeError:
        return line.strip()
    return str(d.get("buildNumber") or d.get("build") or d.get("_value") or line.strip())


def check_update(con, fetch=fetch_latest):
    """-> (status, build). status: 'first' (nothing stored), 'new' (patch since last import), 'same'."""
    line = fetch()
    build = build_of(line)
    stored = get_meta(con, "sde_build")
    return ("first" if stored is None else "new" if stored != build else "same"), build


def remember(con, build):
    set_meta(con, "sde_build", build)
    con.commit()
    try:                                    # a patch may bring a hidden agent back: plan it again (agentleads.recheck_hidden)
        from .agentleads import recheck_hidden
        for aid, why in recheck_hidden(con, build):
            r = con.execute("SELECT name FROM agent_names WHERE agent_id=?", (aid,)).fetchone()
            print(f"AGENT BACK IN THE PLAN: {r[0] if r else aid} - {why}. The next dock at its station reads it; "
                  f"if it is still not in the game run  python -m eve_profit noagents --item \"{r[0] if r else aid}\"  again.")
    except Exception:                       # noqa: BLE001  (never break the data reload)
        pass
