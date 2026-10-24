"""How much ISK per minute have you REALLY made? Over your last N timed steps (activity_log): their minutes, and the ISK of the wallet in that
window: market sales minus purchases (wallet transactions, sales tax estimated at the profile rate), plus the logged payouts of the runs
(mission rewards, bounties, goals: the ISK `stop` found in the journal). python scripts/isk_rate.py [N=20]"""
import json
import os
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
con = sqlite3.connect(os.environ.get("EVE_PROFIT_DB") or "E:/EveProfit/eve_profit_dahl.db")
tax = float(json.load(open(os.path.join(ROOT, "profile_dahl.json"), encoding="utf-8")).get("sales_tax", 0.075) or 0.075)
runs = con.execute("SELECT activity, isk, hours, ts FROM activity_log ORDER BY ts DESC, id DESC LIMIT ?", (n,)).fetchall()[::-1]
if not runs:
    sys.exit("no timed steps yet")
t0 = runs[0][3] - runs[0][2] * 3600                                    # start of the first step
t1 = time.time()
minutes = sum(r[2] for r in runs) * 60
logged = sum(r[1] for r in runs)
iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))  # noqa: E731
tx = con.execute("SELECT t.name, x.quantity, x.unit_price, x.is_buy FROM transactions x JOIN types t ON t.type_id=x.type_id WHERE x.date>=? ORDER BY x.date",
                 (iso(t0),)).fetchall()
sold = sum(q * pr for _n, q, pr, b in tx if not b)
bought = sum(q * pr for _n, q, pr, b in tx if b)
trade = sold * (1 - tax) - bought
wall = (t1 - t0) / 60
print(f"LAST {len(runs)} TIMED STEPS: {time.strftime('%Y-%m-%d %H:%M', time.localtime(t0))} -> now  ({wall:,.0f} min on the clock, {minutes:,.0f} min timed)")
print(f"   market: sold {sold:,.0f}, bought {bought:,.0f}, tax ~{sold * tax:,.0f} -> {trade:+,.0f} ISK")
print(f"   payouts logged by stop (missions, rewards): {logged:+,.0f} ISK")
total = trade + logged
print(f"   TOTAL {total:+,.0f} ISK  =  {total / max(minutes, 1):+,.0f} ISK per timed minute ({total / max(minutes, 1) * 60:+,.0f} ISK/hr)"
      f"  |  {total / max(wall, 1):+,.0f} per clock minute")
print("   note: unsold stock bought in this window counts as spent; mission rewards the journal had not shown at `stop` are missing (add with fixlast --isk).")
print("   steps:")
for a, isk, h, ts in runs:
    print(f"      {time.strftime('%m-%d %H:%M', time.localtime(ts))}  {h * 60:>5.0f} min  {isk:>10,.0f}  {a[:70]}")
