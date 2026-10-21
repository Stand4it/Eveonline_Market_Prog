"""Use a booster you hold instead of selling it, right BEFORE the step it helps (owner 2026-10-21). boosters.json lists each booster, what it helps
(fly / mine / always) and how many minutes per hour it saves. Using it is worth minutes_saved/60 x the ISK/hr of the step; selling it is worth its best
buy order after tax. The better one wins; 'always' boosters (e.g. cerebral accelerators) are always used. After using it:
python -m eve_profit done --goal "opened <booster name>"  (takes it out of your stock until ESI catches up)."""
import json
import os
import re
import time

from .health import record as _hrec

_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "boosters.json")


def _load():
    try:
        return json.load(open(_FILE, encoding="utf-8")).get("boosters", [])
    except (OSError, ValueError):
        return []


def _kind(step):
    first = (step or "").split("\n", 1)[0].lower()
    if first.startswith("step: fly to"):
        return "fly"
    if "mine" in first or "mining" in first:
        return "mine"
    return ""


def _jumps_left(step):
    m = re.search(r"(\d+) jumps? left", step or "") or re.search(r"jump \d+ of (\d+)", step or "")
    return int(m.group(1)) if m else 1


def note(con, g, p, step, rate, tax=0.08, raw=None):
    """-> lines to put right under the STEP line ('FIRST: use ...'), or '' when no booster you hold here is worth using for this step."""
    kind = _kind(step)
    out = []
    try:
        here = g.id_of(p.current_system)
        for b in _load():
            r = con.execute("SELECT t.type_id, COALESCE(SUM(i.quantity),0) FROM inventory i JOIN types t ON t.type_id=i.type_id "
                            "WHERE t.name=? COLLATE NOCASE AND i.system_id=? GROUP BY t.type_id", (b["name"], here)).fetchone()
            if not r or not r[1]:
                continue
            helps = b.get("helps", [])
            if "always" in helps:
                out.append(f"   FIRST (10 seconds): use your {b['name']} ({b['effect']}): {b['how']}. Then:  python -m eve_profit done --goal \"opened {b['name']}\"")
                continue
            if kind not in helps or _jumps_left(raw or step) < b.get("min_jumps", 0):
                continue
            use = b.get("minutes_saved_per_hour", 0) / 60.0 * min(b.get("duration_min", 60), 60) / 60.0 * max(rate, 0.0)
            bid = con.execute("SELECT MAX(price) FROM orders WHERE type_id=? AND is_buy=1 AND volume_remain>0 AND fetched_at>?", (r[0], time.time() - 2 * 86400)).fetchone()[0]
            sell = float(bid or 0.0) * (1 - tax)
            if use > sell:
                out.append(f"   FIRST (10 seconds): use your {b['name']} for this trip ({b['effect']}): {b['how']}. "
                           f"Worth ~{use:,.0f} ISK of time on this step vs ~{sell:,.0f} if sold. Then:  python -m eve_profit done --goal \"opened {b['name']}\"")
    except Exception as _he:                                            # noqa: BLE001
        _hrec('boosters', _he)
    return "\n".join(out)


def insert(con, g, p, step, rate, raw=None):
    """The step with the booster line(s) right under its STEP line."""
    n = note(con, g, p, step, rate, raw=raw)                         # raw = the full step before it was cut to one hop (it still says 'N jumps left')
    if not n:
        return step
    head, _, rest = step.partition("\n")
    return head + "\n" + n + ("\n" + rest if rest else "")
