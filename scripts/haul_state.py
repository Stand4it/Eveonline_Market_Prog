"""Show the haul in progress (meta 'haul_chain'); --bought marks it as bought (under way), --clear forgets it.
python scripts/haul_state.py [--bought | --clear]"""
import json
import os
import sqlite3
import sys
import time

con = sqlite3.connect(os.environ.get("EVE_PROFIT_DB") or "E:/EveProfit/eve_profit_dahl.db")
r = con.execute("SELECT value FROM meta WHERE key='haul_chain'").fetchone()
h = json.loads(r[0]) if r and r[0] and r[0] != "null" else None
if not h:
    print("no haul in progress")
    sys.exit(0)
if "--clear" in sys.argv:
    con.execute("DELETE FROM meta WHERE key='haul_chain'")
    con.commit()
    print("haul forgotten")
    sys.exit(0)
if "--bought" in sys.argv:
    h["bought"], h["t"] = True, time.time()
    con.execute("INSERT OR REPLACE INTO meta VALUES('haul_chain', ?)", (json.dumps(h),))
    con.commit()
print(f"{h['origin']} -> {h['dest']} ({h.get('total')} jumps), bought={h.get('bought', False)}, arrived={h.get('arrived')}, "
      f"age {(time.time() - h.get('t0', h['t'])) / 60:.0f} min")
for it in h["items"]:
    print(f"   {it[1]:,} x {it[0]}  ~{it[2]:,.0f} at {h['dest']}")
