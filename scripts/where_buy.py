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
acquire.JUMP_VALUE_ISK = MIN_PER_JUMP * rate / 60.0                     # a jump = the ISK your time earns in it (also keeps nearby sellers past the price-sanity filter)
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
    now = now or best

# EVERY cheaper seller the DB knows (all scanned regions, highsec AND lowsec), with its trip priced in your time: so a wrong verdict shows
g = Graph(con)
here = g.id_of(p.current_system)
safe = g.reach(here, 60, True)
anyr = g.reach(here, 60, False)
ref = now["price"] if now else float("inf")
rows2 = con.execute("SELECT o.system_id, MIN(o.price), SUM(o.volume_remain) FROM orders o JOIN types t ON t.type_id=o.type_id WHERE t.name=? COLLATE NOCASE "
                    "AND o.is_buy=0 AND o.volume_remain>=? AND o.price<? GROUP BY o.system_id ORDER BY 2", (item, qty, ref)).fetchall()
regions = con.execute("SELECT COUNT(DISTINCT region_id) FROM orders").fetchone()[0]
print(f"   EVERY cheaper seller known ({len(rows2)} systems, {regions} regions scanned; lowsec marked LOW, no route = other side of null/wormhole):")
for sid, price, vol in rows2[:int(opt("--top", 15))]:
    j_safe = safe[sid].jumps if sid in safe else None
    j_any = anyr[sid].jumps if sid in anyr else None
    j = j_safe if j_safe is not None else j_any
    sec = g.sec.get(sid, 0.0)
    tag = "" if sec >= 0.45 else ("LOW " if sec > 0.0 else "NULL ")
    if j is None:
        print(f"      {price:>11,.0f}  {g.name.get(sid, sid)} ({sec:.1f}): more than 60 jumps away (or no gate route): not worth it")
        continue
    cost = 2 * j * MIN_PER_JUMP * rate / 60.0 if not dest else j * MIN_PER_JUMP * rate / 60.0     # there and on: counted both ways unless it is on your way
    save = (ref - price) * qty
    verdict = "WORTH IT" if save > cost else "not worth it"
    route = "" if j_safe is not None else f" (only via lowsec/null: {j_any} jumps)"
    print(f"      {price:>11,.0f}  saves {save:>11,.0f}  {tag}{g.name.get(sid, sid)} ({sec:.1f}) {j} jumps{route} ~{2 * j * MIN_PER_JUMP:.0f} min there+back = {cost:,.0f} ISK of time: {verdict}")
if False:
    base = now["price"] * qty if now else None
    print(("" if now else "(no seller here or on your way) ") + f"BUY LATER in {best['system']}: {best['price']:,.0f} each = {best['price'] * qty:,.0f} ISK, {best['detour']} extra jumps ~{mins:.0f} min "
          f"({mins * rate / 60:,.0f} ISK of your time). {best['station'][:60]}"
          + (f"\n   saves {base - best['price'] * qty - mins * rate / 60:,.0f} ISK net vs buying now for {base:,.0f}" if base else ""))
