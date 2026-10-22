"""Update an existing agent offer from a new screenshot in one call; jumps are re-checked from the map DB.
python scripts/offer_update.py "<agent name part>" [field=value ...] [--note "text appended to note"] [--accepted "2026-10-28 12:57"] [--done] [--no-finish]
  field=value: isk=28000 bonus=35000 jumps=1 available=false ...  (numbers and true/false are converted)
  --accepted EXPIRY: marks the mission accepted (in progress) and records when it expires
  --done: mission finished: available=false"""
import argparse
import json
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from finish import finish  # noqa: E402

a = argparse.ArgumentParser()
a.add_argument("agent")
a.add_argument("fields", nargs="*")
a.add_argument("--note", default="")
a.add_argument("--accepted", default="")
a.add_argument("--done", action="store_true")
a.add_argument("--no-finish", action="store_true")
o = a.parse_args()

from offers_lock import offers_lock  # noqa: E402
p = os.path.join(ROOT, "agent_offers.json")
_lock = offers_lock()                                                   # held from read to write: parallel saves lost offers
_lock.__enter__()
_held = [True]


def _release():
    if _held[0]:
        _held[0] = False
        _lock.__exit__(None, None, None)


import atexit  # noqa: E402
atexit.register(_release)                                               # also on an early sys.exit
d = json.load(open(p, encoding="utf-8"))
hits = [x for x in d["offers"] if o.agent.lower() in x["agent"].lower() and x.get("available", True)] or \
       [x for x in d["offers"] if o.agent.lower() in x["agent"].lower()]
if len(hits) != 1:
    sys.exit(f"{len(hits)} offers match '{o.agent}'; be more specific")
x = hits[0]
changes = []
for f in o.fields:
    k, v = f.split("=", 1)
    v = {"true": True, "false": False}.get(v.lower(), v)
    if isinstance(v, str):
        try:
            v = float(v) if "." in v else int(v)
        except ValueError:
            pass
    x[k] = v
    changes.append(f"{k}={v}")
if x.get("agent_system") and x.get("to_system") and not any(c.startswith("jumps=") for c in changes):
    try:
        from eve_profit.db import connect
        from eve_profit.graph import Graph
        g = Graph(connect(os.environ.get("EVE_PROFIT_DB") or "E:/EveProfit/eve_profit_dahl.db"))
        r = g.route(g.id_of(x["agent_system"]), g.id_of(x["to_system"]), 60, True)
        if r and len(r.path) - 1 != x.get("jumps"):
            changes.append(f"jumps {x.get('jumps')}->{len(r.path) - 1} (map DB)")
            x["jumps"] = len(r.path) - 1
    except Exception as e:                                              # noqa: BLE001
        print("route check skipped:", e)
if o.accepted:
    x["accepted"], x["expires"] = str(date.today()), o.accepted
    changes.append(f"ACCEPTED, expires {o.accepted}")
if o.done:
    x["available"] = False
    changes.append("DONE")
if o.note:
    x["note"] = (x.get("note", "") + " " + o.note).strip()
with open(p, "w", encoding="utf-8", newline="\n") as f:
    json.dump(d, f, indent=1, ensure_ascii=False)
    f.write("\n")
_release()                                                              # released before the slow finish (tests, push)
name = x["agent"].split(" (")[0]
print(f"{name}: " + ("; ".join(changes) or "note only"))
if not o.no_finish:
    finish(f"Offer update: {name}", f"agent_offers.json: {name}: {'; '.join(changes)}{(' - ' + o.note) if o.note else ''}")
