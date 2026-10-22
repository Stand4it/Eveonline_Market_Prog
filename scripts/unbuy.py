"""Undo a purchase recorded by mistake (done --goal "bought ..." or a buy-step stop) so `next` plans to buy it again.
python scripts/unbuy.py "Miner I" """
import json
import os
import sqlite3
import sys

con = sqlite3.connect(os.environ.get("EVE_PROFIT_DB") or "E:/EveProfit/eve_profit_dahl.db")
r = con.execute("SELECT value FROM meta WHERE key='acquired'").fetchone()
st = json.loads(r[0]) if r and r[0] else {}
gone = [k for k in st if k.lower() == sys.argv[1].lower()]
for k in gone:
    st.pop(k)
con.execute("INSERT OR REPLACE INTO meta VALUES('acquired', ?)", (json.dumps(st),))
con.commit()
print(f"forgot the purchase of {', '.join(gone)}" if gone else f"no recorded purchase of {sys.argv[1]}")
