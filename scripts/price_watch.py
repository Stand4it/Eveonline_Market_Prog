"""Fractured Skies market watch (owner 2026-10-28): synchronizer rigs (10 Nov) are built from Tech I salvage materials and rogue drone components,
so their prices may rise. Saves a Jita snapshot (lowest sell, highest buy) of those groups and prints the change against the FIRST snapshot.
python scripts/price_watch.py            snapshot now (one per day) + compare
python scripts/price_watch.py --show     compare only"""
import json
import os
import sqlite3
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "data", "price_watch")
GROUPS = {754: "salvage", 886: "rogue drone components"}
JITA = 30000142


def snapshot(con):
    out = {}
    ids = ",".join(str(g) for g in GROUPS)
    for name, grp, sell, buy in con.execute(
            f"SELECT t.name, t.group_id, MIN(CASE WHEN o.is_buy=0 THEN o.price END), MAX(CASE WHEN o.is_buy=1 THEN o.price END) "
            f"FROM types t LEFT JOIN orders o ON o.type_id=t.type_id AND o.system_id={JITA} WHERE t.group_id IN ({ids}) GROUP BY t.type_id"):
        if sell or buy:
            out[name] = {"group": GROUPS[grp], "sell": sell, "buy": buy}
    return out


def main():
    os.makedirs(DIR, exist_ok=True)
    con = sqlite3.connect(os.environ.get("EVE_PROFIT_DB") or "E:/EveProfit/eve_profit_dahl.db")
    today = os.path.join(DIR, f"{date.today().isoformat()}.json")
    if "--show" not in sys.argv:
        snap = snapshot(con)
        json.dump(snap, open(today, "w", encoding="utf-8"), indent=1)
        print(f"saved {len(snap)} prices -> {today}")
    files = sorted(f for f in os.listdir(DIR) if f.endswith(".json"))
    if len(files) < 2:
        print("first snapshot: run again after 10 Nov (or any later day) to see the change")
        return
    a = json.load(open(os.path.join(DIR, files[0]), encoding="utf-8"))
    b = json.load(open(os.path.join(DIR, files[-1]), encoding="utf-8"))
    rows = []
    for n, v in b.items():
        old = (a.get(n) or {}).get("sell")
        if old and v.get("sell"):
            rows.append((v["sell"] / old - 1, n, old, v["sell"], v["group"]))
    rows.sort(reverse=True)
    print(f"Jita lowest sell, {files[0][:10]} -> {files[-1][:10]} (biggest risers first):")
    for ch, n, o, s, g in rows[:15]:
        print(f"   {ch * 100:+6.1f}%  {n} ({g}): {o:,.0f} -> {s:,.0f}")
    up = sum(1 for r in rows if r[0] > 0.10)
    print(f"{up} of {len(rows)} up more than 10%" + ("  -> salvage is worth keeping / salvaging pays more: tell Claude" if up >= len(rows) / 3 else ""))


if __name__ == "__main__":
    main()
