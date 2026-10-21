"""How close is a REGION? A buy order with range 'Region' takes sales from ANY system in its region, so you only need to reach that region's nearest
system. python scripts/region_reach.py FROM SYSTEM_IN_REGION [SYSTEM_IN_REGION ...]  -> region, nearest system of it from FROM, jumps (safe route)."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from eve_profit.db import connect  # noqa: E402
from eve_profit.graph import Graph  # noqa: E402

con = connect(os.environ.get("EVE_PROFIT_DB") or "E:/EveProfit/eve_profit_dahl.db")
g = Graph(con)
src = g.id_of(sys.argv[1])
cols = [r[1] for r in con.execute("PRAGMA table_info(systems)")]
reg_col = "region_id" if "region_id" in cols else None
reach = g.reach(src, 40, True)
for name in sys.argv[2:]:
    sid = g.id_of(name)
    if reg_col:
        rid = con.execute("SELECT region_id FROM systems WHERE system_id=?", (sid,)).fetchone()[0]
        members = {r[0] for r in con.execute("SELECT system_id FROM systems WHERE region_id=?", (rid,))}
    else:
        rid, members = "?", {sid}
    best = min(((reach[m].jumps, m) for m in members if m in reach), default=None)
    direct = reach[sid].jumps if sid in reach else None
    if best:
        print(f"{name}: region {rid}; nearest system of that region from {sys.argv[1]}: {g.name[best[1]]} ({best[0]} jumps, safe route); {name} itself: {direct} jumps")
    else:
        print(f"{name}: region {rid}; not reachable within 40 safe jumps")
