"""Add an agent offer from a screenshot in one call; jumps come from the map DB.
python scripts/add_offer.py --agent "Mumine Dalamoure" --career Distribution --system Isikemi
    --where "Isikemi II - Moon 1 (0.8)" --mission "Save The Children" --cargo "clothing"
    --to Uosusuokko --to-station "Uosusuokko VII (0.7)" --m3 180 --isk 22000 --bonus 21000
    --bonus-time "54 min" --lp 26 [--task-min 8] [--taxed] [--note "..."] [--no-finish]
Then refreshes docs, runs tests, logs DECISIONS.md, commits and pushes (scripts/finish.py)."""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from eve_profit.db import connect  # noqa: E402
from eve_profit.graph import Graph  # noqa: E402
from finish import finish  # noqa: E402

a = argparse.ArgumentParser()
for k in ("agent", "career", "system", "where", "mission", "cargo", "to", "to-station", "bonus-time"):
    a.add_argument("--" + k, required=k not in ("cargo", "bonus-time"), default="")
a.add_argument("--m3", type=float, default=0.0)
a.add_argument("--isk", type=int, required=True)
a.add_argument("--bonus", type=int, default=0)
a.add_argument("--lp", type=int, default=0)
a.add_argument("--task-min", type=int, default=8)
a.add_argument("--level", default="L1")
a.add_argument("--taxed", action="store_true")
a.add_argument("--note", default="")
a.add_argument("--no-finish", action="store_true")
o = a.parse_args()

g = Graph(connect(os.environ.get("EVE_PROFIT_DB") or "E:/EveProfit/eve_profit_dahl.db"))
r = g.route(g.id_of(o.system), g.id_of(o.to), 60, True)
jumps = len(r.path) - 1 if r else None
if jumps is None:
    sys.exit(f"no safe route {o.system} > {o.to}; check the names")

bonus_txt = f"; bonus {o.bonus:,} ISK within {o.bonus_time}" if o.bonus else ""
what = f"courier {o.cargo} ({o.m3:g} m3)" if o.m3 else "task"
offer = {
    "taxed": o.taxed, "loot": [], "cost": [], "granted": [], "available": True,
    "agent_system": o.system, "career": o.career, "where": o.where,
    "agent": f"{o.agent} ({o.career}, {o.level}, {o.where})",
    "mission": f"'{o.mission}': {what} to {o.to_station}. Pays {o.isk:,} ISK + {o.lp} LP{bonus_txt}.",
    "isk": o.isk, "bonus": o.bonus, "task_min": o.task_min, "jumps": jumps,
    "to_system": o.to, "m3": o.m3,
    "needs": f"{o.m3:g} m3 of cargo; {o.to} is {jumps} jump(s) from {o.system} (map DB route)",
    "note": o.note or f"Seen, {o.isk + o.bonus:,} ISK + {o.lp} LP with the bonus.",
}
from offers_lock import offers_lock  # noqa: E402
p = os.path.join(ROOT, "agent_offers.json")
with offers_lock():                                                     # one writer at a time (parallel saves lost offers)
    d = json.load(open(p, encoding="utf-8"))
    d["offers"].append(offer)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(d, f, indent=1, ensure_ascii=False)
        f.write("\n")
line = (f"agent_offers.json: {o.agent} ({o.system}, {o.career} {o.level}) '{o.mission}' "
        f"{o.m3:g} m3 to {o.to} ({jumps} jumps), {o.isk:,} + {o.bonus:,} bonus ({o.bonus_time}) + {o.lp} LP.")
print(f"added: {o.agent}, {jumps} jumps, {o.isk + o.bonus:,} ISK + {o.lp} LP with bonus")
if not o.no_finish:
    finish(f"Add {o.agent} offer", line)
