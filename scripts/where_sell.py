"""Sell it HERE now, or carry it somewhere that pays more? Reads the item's BUY orders live from EVERY region (ESI, ~65 public calls), then compares
every buyer that pays more than the best price you can sell to from where you are (this station, or a ranged / region-wide order that reaches you):
   gained = (its price - price here) x the units it takes (up to what you have), after sales tax
   time   = the jumps to a system from which you can sell to it (its own range counts) x your ISK/min (best option in your plan, from the last `next`)
   NET    = gained - time.   NET < 0 -> sell HERE.   NET >= 0 -> sell THERE.
python scripts/where_sell.py "'Arbalest' Rocket Launcher I" [qty] [--to NEXT_DESTINATION] [--from SYSTEM] [--top 25] [--cached]
(qty defaults to what you hold here; with --to only the extra jumps toward where you go next count, else there and back)"""
import dataclasses
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from eve_profit.config import Profile  # noqa: E402
from eve_profit.db import connect  # noqa: E402
from eve_profit.graph import Graph  # noqa: E402

MIN_PER_JUMP = 2.5
MAX_JUMPS = 200

args = sys.argv[1:]
opt = lambda k, d: args[args.index(k) + 1] if k in args else d  # noqa: E731
pos = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or not args[i - 1].startswith("--"))]
con = connect(os.environ.get("EVE_PROFIT_DB") or "E:/EveProfit/eve_profit_dahl.db")
g = Graph(con)
p = Profile.load(os.path.join(ROOT, "profile_dahl.json"))
p = dataclasses.replace(p, current_system=opt("--from", p.current_system))
here = g.id_of(p.current_system)
row = con.execute("SELECT type_id, name FROM types WHERE name=? COLLATE NOCASE", (pos[0],)).fetchone() or \
    con.execute("SELECT type_id, name FROM types WHERE name LIKE ? COLLATE NOCASE ORDER BY LENGTH(name) LIMIT 1", (f"%{pos[0]}%",)).fetchone()
if not row:
    sys.exit(f"unknown item {pos[0]}")
tid, name = row
if len(pos) > 1:
    qty = int(pos[1])
else:
    r = con.execute("SELECT COALESCE(SUM(quantity),0) FROM inventory WHERE type_id=? AND system_id=?", (tid, here)).fetchone()
    qty = int(r[0] or 0) or 1
r = con.execute("SELECT value FROM meta WHERE key='best_rate'").fetchone()
rate = float(r[0]) if r and r[0] else 1_000_000.0
per_jump = MIN_PER_JUMP * rate / 60.0
tax = p.sales_tax
dest = opt("--to", None)

if "--cached" not in args:
    from eve_profit.esi import ESI, refresh_item
    regions = [x[0] for x in con.execute("SELECT DISTINCT region_id FROM systems WHERE region_id < 11000000")]
    t0 = time.time()
    try:
        refresh_item(con, ESI(), regions, tid)
        print(f"(live prices from all {len(regions)} regions, {time.time() - t0:.0f} s)")
    except Exception as e:                                              # noqa: BLE001
        print(f"(live fetch failed: {e}; using the last scan)")

region_of = {s: rg for s, rg in con.execute("SELECT system_id, region_id FROM systems")}
safe = g.reach(here, MAX_JUMPS, True)
anyr = g.reach(here, MAX_JUMPS, False)
did = g.id_of(dest) if dest else None
to_dest = g.reach(did, MAX_JUMPS, True) if did else None
direct = safe[did].jumps if did in safe else 0
dist_cache = {}


def jumps_between(a, b):
    """Safe-route jumps a -> b (lowsec route if no safe one), None if unreachable."""
    if a not in dist_cache:
        dist_cache[a] = g.reach(a, 40, False)
    return dist_cache[a][b].jumps if b in dist_cache[a] else None


def sell_point(sid, rng):
    """The system nearest to you from which you can sell into an order in `sid` with range `rng` -> (system, jumps from you, lowsec only) or None."""
    reach_n = None if rng in (None, "station", "solarsystem") else (10 ** 6 if rng == "region" else int(rng))
    cands = [sid]
    if reach_n:                                                         # any system of the order's region within its range
        cands = [s for s, rg in region_of.items() if rg == region_of.get(sid) and (rng == "region" or (jumps_between(sid, s) or 99) <= reach_n)]
    best = None
    for s in cands:
        j = safe[s].jumps if s in safe else (anyr[s].jumps if s in anyr else None)
        if j is not None and (best is None or j < best[1]):
            best = (s, j, s not in safe)
    return best


orders = con.execute("SELECT o.order_id, o.system_id, o.price, o.volume_remain, o.min_volume, r.rng FROM orders o LEFT JOIN order_range r ON r.order_id=o.order_id "
                     "WHERE o.type_id=? AND o.is_buy=1 AND o.volume_remain>0 ORDER BY o.price DESC", (tid,)).fetchall()
rows = []
for oid, sid, price, vol, minv, rng in orders:
    sp = sell_point(sid, (rng or "station").lower())
    if not sp:
        continue
    s, j, low = sp
    trip = max(0, j + (to_dest[s].jumps if s in to_dest else j) - direct) if did else 2 * j
    rows.append({"sys": g.name[sid], "from": g.name[s], "sec": g.sec.get(sid, 0.0), "price": price, "vol": vol, "min": minv or 1,
                 "rng": rng or "station", "j": j, "trip": trip, "low": low})
if not rows:
    sys.exit(f"nobody buys {name} anywhere reachable")
now = [x for x in rows if x["trip"] == 0]
here_price = max((x["price"] for x in now if x["min"] <= qty), default=None)
print(f"{qty:,} x {name} from {p.current_system}: your time = {rate:,.0f} ISK/hr = {rate / 60:,.0f} ISK/min (a jump ~{MIN_PER_JUMP} min = {per_jump:,.0f} ISK); sales tax {tax:.1%}"
      f"{'; going to ' + dest + ' (only the extra jumps count)' if dest else '; trip counted there and back'}")
if here_price is not None:
    b = max((x for x in now if x["price"] == here_price), key=lambda x: x["vol"])
    print(f"HERE: best buyer you can sell to now: {here_price:,.2f} each ({b['sys']}, range {b['rng']}) = {here_price * min(qty, b['vol']) * (1 - tax):,.0f} ISK after tax"
          + (f" for {min(qty, b['vol']):,} (it takes only {b['vol']:,})" if b["vol"] < qty else ""))
else:
    print("HERE: nobody buys it where you are")
ref = here_price or 0.0
out = []
for x in rows:
    if x["price"] <= ref or x["trip"] == 0:
        continue
    units = min(x["vol"], qty)
    if units < x["min"]:
        continue
    gained = (x["price"] - ref) * units * (1 - tax)
    time_cost = x["trip"] * per_jump
    out.append(dict(x, units=units, gained=gained, time=time_cost, net=gained - time_cost))
out.sort(key=lambda o: -o["net"])
print(f"   every buyer that PAYS MORE than here ({len(out)} orders), best net first.  NET = extra ISK after tax - ISK your time would have made;  NET < 0 -> sell here, NET >= 0 -> sell there:")
print(f"      {'price':>12} {'units':>6} {'jumps':>5} {'trip min':>8} {'gained':>12} {'time cost':>11} {'NET':>13}  buyer (sell from)")
for o in out[:int(opt("--top", 25))]:
    tag = "" if o["sec"] >= 0.45 else ("LOW " if o["sec"] > 0 else "NULL ")
    frm = "" if o["from"] == o["sys"] else f" (sell from {o['from']}, range {o['rng']})"
    print(f"      {o['price']:>12,.2f} {o['units']:>6,} {o['j']:>5} {o['trip'] * MIN_PER_JUMP:>8.0f} {o['gained']:>12,.0f} {o['time']:>11,.0f} {o['net']:>+13,.0f}  "
          f"{tag}{o['sys']} ({o['sec']:.1f}){frm}{' via lowsec' if o['low'] else ''}{'   <- SELL THERE' if o['net'] >= 0 else ''}")
win = [o for o in out if o["net"] >= 0]
if win:
    b = win[0]
    print(f"VERDICT: SELL IN {b['from']} ({b['j']} jumps) to the {b['price']:,.0f} buyer in {b['sys']}: {b['gained']:,.0f} more ISK, costs {b['time']:,.0f} of your time, net {b['net']:+,.0f}"
          + (f" (it takes only {b['units']:,} of your {qty:,})" if b["units"] < qty else ""))
elif here_price is not None:
    print("VERDICT: SELL HERE. Every better buyer costs more in time than it pays extra" + (f" (best net {out[0]['net']:+,.0f})." if out else " (nobody pays more)."))
else:
    b = max(out, key=lambda o: o["price"] * o["units"] * (1 - tax) - o["time"]) if out else None
    print(f"VERDICT: nobody buys it here: sell in {b['from']} ({b['j']} jumps) at {b['price']:,.2f}" if b else "VERDICT: no buyer reachable")
