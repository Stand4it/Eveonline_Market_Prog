"""Run one read-only SQL query on the character DB and print the rows (avoids PowerShell quoting trouble with inline python).
python scripts/sql.py "SELECT type_id,name FROM types WHERE name LIKE '%Crate%'" [--limit 40]"""
import os
import sqlite3
import sys

q = sys.argv[1]
lim = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 40
con = sqlite3.connect("file:" + (os.environ.get("EVE_PROFIT_DB") or "E:/EveProfit/eve_profit_dahl.db") + "?mode=ro", uri=True)
cur = con.execute(q)
print(" | ".join(d[0] for d in cur.description or []))
for i, r in enumerate(cur):
    if i >= lim:
        print(f"... (more rows; --limit {lim})")
        break
    print(" | ".join(str(x) for x in r))
