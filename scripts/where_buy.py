"""Where is it cheapest to get, ALL THINGS COUNTED? Reads the item's sell orders live from EVERY region of the universe (ESI, ~65 public calls),
measures the jumps from where you are, and ranks every seller by TOTAL COST = price x qty + the trip priced at your time (the ISK/min of the
top earning option in your plan, saved by the last `next`). The trip is there and back to your ship, or only the extra jumps with --to.
python scripts/where_buy.py "Small Armor Repairer I" [qty] [--to NEXT_DESTINATION] [--from SYSTEM] [--top 15] [--cached]   (--cached: no live fetch)"""
import dataclasses
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from eve_profit.config import Profile  # noqa: E402
from eve_profit.db import connect  # noqa: E402
from eve_profit.graph import Graph  # noqa: E402

MIN_PER_JUMP = 2.5                       # align, warp, gate (your timed flights: 2-3 min a jump)
MAX_JUMPS = 200

args = sys.argv[1:]
opt = lambda k, d: args[args.index(k) + 1] if k in args else d  # noqa: E731
pos = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or not args[i - 1].startswith("--"))]
item, qty = pos[0], int(pos[1]) if len(pos) > 1 else 1
con = connect(os.environ.get("EVE_PROFIT_DB") or "E:/EveProfit/eve_profit_dahl.db")
g = Graph(con)
p = Profile.load(os.path.join(ROOT, "profile_dahl.json"))
p = dataclasses.replace(p, current_system=opt("--from", p.current_system))
here = g.id_of(p.current_system)
dest = opt("--to", None)
r = con.execute("SELECT value FROM meta WHERE key='best_rate'").fetchone()
rate = float(r[0]) if r and r[0] else 1_000_000.0                       # ISK per hour your time earns now
per_jump = MIN_PER_JUMP * rate / 60.0
row = con.execute("SELECT type_id, name FROM types WHERE name=? COLLATE NOCASE", (item,)).fetchone() or \
    con.execute("SELECT type_id, name FROM types WHERE name LIKE ? COLLATE NOCASE ORDER BY LENGTH(name) LIMIT 1", (f"%{item}%",)).fetchone()
if not row:
    sys.exit(f"unknown item {item}")
tid, name = row

if "--cached" not in args:                                              # the whole universe, live: every region's sell orders for this one item
    from eve_profit.esi import ESI, refresh_item
    regions = [x[0] for x in con.execute("SELECT DISTINCT region_id FROM systems WHERE region_id < 11000000")]
    t0 = time.time()
    try:
        refresh_item(con, ESI(), regions, tid)
        print(f"(live prices from all {len(regions)} regions, {time.time() - t0:.0f} s)")
    except Exception as e:                                              # noqa: BLE001
        print(f"(live fetch failed: {e}; using the last scan)")

safe = g.reach(here, MAX_JUMPS, True)
anyr = g.reach(here, MAX_JUMPS, False)
did = g.id_of(dest) if dest else None
to_dest = g.reach(did, MAX_JUMPS, True) if did else None
direct = safe[did].jumps if did in safe else 0
sellers = con.execute("SELECT system_id, MIN(price), SUM(volume_remain), MAX(location_id) FROM orders WHERE type_id=? AND is_buy=0 AND volume_remain>=? "
                      "GROUP BY system_id", (tid, qty)).fetchall()
opts = []
for sid, price, vol, loc in sellers:
    j_safe = safe[sid].jumps if sid in safe else None
    j = j_safe if j_safe is not None else (anyr[sid].jumps if sid in anyr else None)
    if j is None:
        continue
    if did:
        trip = max(0, j + (to_dest[sid].jumps if sid in to_dest else j) - direct)      # extra jumps on the way to where you go next
    else:
        trip = 2 * j                                                    # there and back to your ship
    opts.append({"sys": g.name[sid], "sec": g.sec.get(sid, 0.0), "price": price, "jumps": j, "trip": trip, "lowsec_only": j_safe is None,
                 "total": price * qty + trip * per_jump, "loc": loc})
if not opts:
    sys.exit(f"nobody sells {qty} x {name} anywhere reachable")
opts.sort(key=lambda o: o["total"])
best = opts[0]
st = con.execute("SELECT name FROM stations WHERE station_id=?", (best["loc"],)).fetchone()
print(f"{qty} x {name} from {p.current_system}: your time = {rate:,.0f} ISK/hr = {rate / 60:,.0f} ISK/min, a jump = {per_jump:,.0f} ISK"
      f"{'; going to ' + dest + ' (only extra jumps count)' if dest else '; trip counted there and back'}")
where = "HERE" if best["jumps"] == 0 else f"in {best['sys']} ({best['jumps']} jumps)"
print(f"BEST: buy {where} at {best['price']:,.0f} each = {best['price'] * qty:,.0f} ISK + {best['trip']} jumps of time = {best['total']:,.0f} total"
      + (f"  {st[0]}" if st else ""))
print(f"   every seller, lowest TOTAL cost first ({len(opts)} systems):")
for o in opts[:int(opt("--top", 15))]:
    tag = "" if o["sec"] >= 0.45 else ("LOW " if o["sec"] > 0 else "NULL ")
    print(f"      {o['total']:>12,.0f} total = {o['price'] * qty:>11,.0f} price + {o['trip']:>3} jumps ({o['trip'] * MIN_PER_JUMP:>4.0f} min)  "
          f"{tag}{o['sys']} ({o['sec']:.1f}){' via lowsec' if o['lowsec_only'] else ''}{'   <- here' if o['jumps'] == 0 else ''}")
cheapest = min(opts, key=lambda o: o["price"])
if cheapest is not best:
    print(f"   cheapest price anywhere: {cheapest['price']:,.0f} in {cheapest['sys']} ({cheapest['jumps']} jumps): {cheapest['total'] - best['total']:,.0f} ISK worse all things counted")
