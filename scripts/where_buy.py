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


def trip_of(sid):
    """(jumps away, jumps of trip, lowsec only) or None: there and back to your ship, or only the extra jumps on the way to --to."""
    j_safe = safe[sid].jumps if sid in safe else None
    j = j_safe if j_safe is not None else (anyr[sid].jumps if sid in anyr else None)
    if j is None:
        return None
    trip = max(0, j + (to_dest[sid].jumps if sid in to_dest else j) - direct) if did else 2 * j
    return j, trip, j_safe is None


# the price you pay HERE (or on your way: no extra jumps): what every other seller is compared with
rows = con.execute("SELECT system_id, price, volume_remain, location_id FROM orders WHERE type_id=? AND is_buy=0 AND volume_remain>0 ORDER BY price",
                   (tid,)).fetchall()
local = [(s, pr, v, loc) for s, pr, v, loc in rows if (trip_of(s) or (0, 99, 0))[1] == 0]
if local:
    left, cost_here = qty, 0.0                                          # walk up the cheapest orders here until qty is covered
    for s, pr, v, loc in local:
        take = min(v, left)
        cost_here += take * pr
        left -= take
        if not left:
            break
    here_each = cost_here / max(qty - left, 1)
    here_loc = local[0][3]
else:
    here_each, cost_here, left, here_loc = None, None, qty, None

print(f"{qty:,} x {name} from {p.current_system}: your time = {rate:,.0f} ISK/hr = {rate / 60:,.0f} ISK/min (a jump ~{MIN_PER_JUMP} min = {per_jump:,.0f} ISK)"
      f"{'; going to ' + dest + ' (only the extra jumps count)' if dest else '; trip counted there and back'}")
if here_each is not None:
    st = con.execute("SELECT name FROM stations WHERE station_id=?", (here_loc,)).fetchone()
    print(f"HERE: {here_each:,.2f} each = {cost_here:,.0f} ISK for {qty - left:,}{' (only ' + str(qty - left) + ' for sale here)' if left else ''}  {st[0] if st else ''}")
else:
    print("HERE: nobody sells it here or on your way")

# EVERY cheaper seller in the universe, one ORDER at a time: saved = (price here - its price) x the units it has (up to what you need),
# time = its trip in minutes x your ISK/min; NET = saved - time. NET < 0: buy here. NET >= 0: buy there.
ref = here_each if here_each is not None else float("inf")
out = []
for s, pr, v, loc in rows:
    if pr >= ref:
        break
    t = trip_of(s)
    if t is None or t[1] == 0:
        continue
    j, trip, low = t
    units = min(v, qty)
    saved = (ref - pr) * units if here_each is not None else 0.0
    time_cost = trip * per_jump
    out.append({"sys": g.name[s], "sec": g.sec.get(s, 0.0), "price": pr, "units": units, "j": j, "trip": trip, "low": low,
                "saved": saved, "time": time_cost, "net": saved - time_cost})
out.sort(key=lambda o: -o["net"])
print(f"   every seller CHEAPER than here ({len(out)} orders), best net first.  NET = saved - ISK your time would have made;  NET < 0 -> buy here, NET >= 0 -> buy there:")
print(f"      {'price':>9} {'units':>9} {'jumps':>5} {'trip min':>8} {'saved':>11} {'time cost':>11} {'NET':>12}  where")
for o in out[:int(opt("--top", 25))]:
    tag = "" if o["sec"] >= 0.45 else ("LOW " if o["sec"] > 0 else "NULL ")
    print(f"      {o['price']:>9,.2f} {o['units']:>9,} {o['j']:>5} {o['trip'] * MIN_PER_JUMP:>8.0f} {o['saved']:>11,.0f} {o['time']:>11,.0f} {o['net']:>+12,.0f}  "
          f"{tag}{o['sys']} ({o['sec']:.1f}){' via lowsec' if o['low'] else ''}{'   <- BUY THERE' if o['net'] >= 0 else ''}")
win = [o for o in out if o["net"] >= 0]
if here_each is None and not out:
    sys.exit(f"nobody sells {name} anywhere reachable")
if win:
    b = win[0]
    print(f"VERDICT: BUY IN {b['sys']} ({b['j']} jumps): saves {b['saved']:,.0f} ISK, costs {b['time']:,.0f} of your time, net {b['net']:+,.0f}"
          + (f" (it has only {b['units']:,} of the {qty:,})" if b["units"] < qty else ""))
elif here_each is not None:
    print(f"VERDICT: BUY HERE. Every cheaper seller costs more in time than it saves (best net {out[0]['net']:+,.0f})." if out else "VERDICT: BUY HERE (nobody is cheaper).")
else:
    b = min(out, key=lambda o: o["price"] * qty + o["time"])
    print(f"VERDICT: nothing here: buy in {b['sys']} ({b['j']} jumps) at {b['price']:,.2f}")
