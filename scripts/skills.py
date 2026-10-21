"""Your trained level of named skills (0 = not trained), from the last sync.
python scripts/skills.py "Science" "Industry" "Laboratory Operation" ..."""
import os
import sqlite3
import sys

con = sqlite3.connect(os.environ.get("EVE_PROFIT_DB") or "E:/EveProfit/eve_profit_dahl.db")
cols = [r[1] for r in con.execute("PRAGMA table_info(character_skills)")]
lvl = next(c for c in cols if "level" in c)
sid = next(c for c in cols if c in ("skill_id", "type_id"))
for name in sys.argv[1:]:
    r = con.execute(f"SELECT MAX(s.{lvl}) FROM character_skills s JOIN types t ON t.type_id=s.{sid} WHERE t.name=? COLLATE NOCASE", (name,)).fetchone()
    print(f"{name}: {r[0] or 0}")
