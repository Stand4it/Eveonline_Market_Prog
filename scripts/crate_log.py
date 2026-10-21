"""Open or sell closed? Log what a crate gave, compare with selling it closed, and learn the average over every opening.
python scripts/crate_log.py "<crate name>" "<item inside>" ["<item inside>" ...]     (log one opening; items: exact or partial names, "3x Name" for stacks)
python scripts/crate_log.py "<crate name>"                                            (show the history and the verdict before you open the next one)
Values = the best BUY order the DB has seen (what you get instantly), else the lowest sell order x 0.9. Log kept in data/crate_opens.json (local, not on GitHub)."""
import json
import os
import re
import sqlite3
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "data", "crate_opens.json")
FRESH = __import__("time").time() - 2 * 86400            # only orders seen in the last 2 days (the table keeps old ones)
con = sqlite3.connect(os.environ.get("EVE_PROFIT_DB") or "E:/EveProfit/eve_profit_dahl.db")


def find(name):
    r = con.execute("SELECT type_id,name FROM types WHERE name=? COLLATE NOCASE", (name,)).fetchone() or \
        con.execute("SELECT type_id,name FROM types WHERE name LIKE ? COLLATE NOCASE ORDER BY LENGTH(name) LIMIT 1", (f"%{name}%",)).fetchone()
    return r if r else (None, name)


def value(tid):
    if tid is None:
        return 0.0, "unknown item"
    b = con.execute("SELECT MAX(price) FROM orders WHERE type_id=? AND is_buy=1 AND volume_remain>0 AND fetched_at>?", (tid, FRESH)).fetchone()[0]
    if b:
        return float(b), "best buy order"
    s = con.execute("SELECT MIN(price) FROM orders WHERE type_id=? AND is_buy=0 AND volume_remain>0 AND fetched_at>?", (tid, FRESH)).fetchone()[0]
    return (float(s) * 0.9, "lowest sell x 0.9") if s else (0.0, "no orders seen")


log = json.load(open(LOG, encoding="utf-8")) if os.path.exists(LOG) else []
ctid, cname = find(sys.argv[1])
cval, csrc = value(ctid)
if len(sys.argv) > 2:
    items = []
    for raw in sys.argv[2:]:
        m = re.match(r"\s*(\d+)\s*x\s*(.+)", raw, re.I)
        q, nm = (int(m.group(1)), m.group(2)) if m else (1, raw)
        tid, full = find(nm)
        v, src = value(tid)
        items.append({"name": full, "qty": q, "each": v, "src": src})
        print(f"   {q} x {full}: {v:,.0f} each ({src})")
    got = sum(i["qty"] * i["each"] for i in items)
    log.append({"date": str(date.today()), "crate": cname, "crate_value": cval, "contents_value": got, "items": items})
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    json.dump(log, open(LOG, "w", encoding="utf-8"), indent=1)
    print(f"{cname}: closed {cval:,.0f} ({csrc}) vs opened {got:,.0f}  ->  {'OPENING PAID' if got > cval else 'SELLING CLOSED WAS BETTER'} by {abs(got - cval):,.0f}")
runs = [x for x in log if x["crate"].lower() == cname.lower()]
if runs:
    avg = sum(x["contents_value"] for x in runs) / len(runs)
    print(f"History {cname}: {len(runs)} opening(s), contents average {avg:,.0f} vs closed now {cval:,.0f}  ->  "
          f"{'OPEN it' if avg > cval * 1.1 else 'SELL CLOSED' if avg < cval * 0.9 else 'about even (sell closed: no risk)'}"
          f"{'  (few openings: luck dominates)' if len(runs) < 3 else ''}")
else:
    print(f"{cname}: closed value now {cval:,.0f} ({csrc}); no openings logged yet.")

