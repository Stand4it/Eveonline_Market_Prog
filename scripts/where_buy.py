"""Buy it NOW (here, or the cheapest place you pass anyway) or LATER somewhere cheaper? One answer, in ISK: a cheaper market only wins when
the ISK it saves beats what your time earns in the extra minutes (your best ISK/hr, saved by the last `next`).
python scripts/where_buy.py "Small Armor Repairer I" [qty] [--to NEXT_DESTINATION] [--from SYSTEM]"""
import dataclasses
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from eve_profit import acquire  # noqa: E402
from eve_profit.config import Profile  # noqa: E402
from eve_profit.db import connect  # noqa: E402
from eve_profit.graph import Graph  # noqa: E402

MIN_PER_JUMP = 2.5                       # align, warp, gate (your timed flights: 2-3 min a jump)

args = sys.argv[1:]
opt = lambda k, d: args[args.index(k) + 1] if k in args else d  # noqa: E731
pos = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or not args[i - 1].startswith("--"))]
item, qty = pos[0], int(pos[1]) if len(pos) > 1 else 1
con = connect(os.environ.get("EVE_PROFIT_DB") or "E:/EveProfit/eve_profit_dahl.db")
p = Profile.load(os.path.join(ROOT, "profile_dahl.json"))
p = dataclasses.replace(p, current_system=opt("--from", p.current_system))
dest = opt("--to", None)
r = con.execute("SELECT value FROM meta WHERE key='best_rate'").fetchone()
rate = float(r[0]) if r and r[0] else 1_000_000.0                       # ISK per hour your time is worth now
acquire.JUMP_VALUE_ISK = 0.0                                            # rank by price only; the time is priced below
rows = acquire.sources(con, Graph(con), p, item, qty, dest=dest, max_jumps=14, limit=300)   # every seller in reach, or the one here gets cut off
if not rows:
    sys.exit(f"no seller of {item} found within 14 safe jumps (run a price scan?)")


def total(x):
    return x["price"] * qty + x["detour"] * MIN_PER_JUMP * rate / 60.0     # price + the ISK your extra minutes would have earned


now = min((x for x in rows if x["detour"] == 0), key=lambda x: x["price"], default=None)   # here, or on the way: no extra time
best = min(rows, key=total)
where = lambda x: "HERE" if x["jumps"] == 0 else f"in {x['system']} ({x['jumps']} jumps, on your way)"  # noqa: E731
print(f"{qty} x {item}  (your time: {rate:,.0f} ISK/hr = {rate / 60:,.0f} ISK/min{', going to ' + dest if dest else ''})")
if now and (best is now or total(now) <= total(best)):
    print(f"BUY NOW {where(now)}: {now['price']:,.0f} each = {now['price'] * qty:,.0f} ISK. {now['station'][:60]}")
    cheaper = min((x for x in rows if x["price"] < now["price"]), key=total, default=None)
    if cheaper:
        mins = cheaper["detour"] * MIN_PER_JUMP
        print(f"   (cheapest elsewhere: {cheaper['system']} at {cheaper['price']:,.0f} saves {(now['price'] - cheaper['price']) * qty:,.0f} ISK but costs "
              f"{cheaper['detour']} extra jumps ~{mins:.0f} min = {mins * rate / 60:,.0f} ISK of your time: not worth it)")
else:
    mins = best["detour"] * MIN_PER_JUMP
    base = now["price"] * qty if now else None
    print(("" if now else "(no seller here or on your way) ") + f"BUY LATER in {best['system']}: {best['price']:,.0f} each = {best['price'] * qty:,.0f} ISK, {best['detour']} extra jumps ~{mins:.0f} min "
          f"({mins * rate / 60:,.0f} ISK of your time). {best['station'][:60]}"
          + (f"\n   saves {base - best['price'] * qty - mins * rate / 60:,.0f} ISK net vs buying now for {base:,.0f}" if base else ""))
