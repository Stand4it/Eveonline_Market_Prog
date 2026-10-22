"""Sell it NOW (here: this station, or a ranged/region buy order that reaches you) or LATER somewhere that pays more? One answer in ISK:
a better market only wins when the extra ISK (after sales tax) beats what your time earns in the extra minutes (best ISK/hr from the last `next`).
Then every market within 15 safe jumps that pays more, so you can check the step is right.
python scripts/where_sell.py "Ecru Marrow Satin - Limited" [qty] [--to NEXT_DESTINATION] [--from SYSTEM] [--top 8]"""
import dataclasses
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from eve_profit.config import Profile  # noqa: E402
from eve_profit.db import connect  # noqa: E402
from eve_profit.graph import Graph  # noqa: E402
from eve_profit.orders import load_books, sell_into_bids  # noqa: E402

MIN_PER_JUMP = 2.5
REACH = 15

args = sys.argv[1:]
opt = lambda k, d: args[args.index(k) + 1] if k in args else d  # noqa: E731
pos = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or not args[i - 1].startswith("--"))]
item = pos[0]
con = connect(os.environ.get("EVE_PROFIT_DB") or "E:/EveProfit/eve_profit_dahl.db")
g = Graph(con)
p = Profile.load(os.path.join(ROOT, "profile_dahl.json"))
p = dataclasses.replace(p, current_system=opt("--from", p.current_system))
row = con.execute("SELECT type_id, name FROM types WHERE name=? COLLATE NOCASE", (item,)).fetchone() or \
    con.execute("SELECT type_id, name FROM types WHERE name LIKE ? COLLATE NOCASE ORDER BY LENGTH(name) LIMIT 1", (f"%{item}%",)).fetchone()
if not row:
    sys.exit(f"unknown item {item}")
tid, name = row[0], row[1]
here = g.id_of(p.current_system)
if len(pos) > 1:
    qty = int(pos[1])
else:
    r = con.execute("SELECT COALESCE(SUM(quantity),0) FROM inventory WHERE type_id=? AND system_id=?", (tid, here)).fetchone()
    qty = int(r[0] or 0) or 1
r = con.execute("SELECT value FROM meta WHERE key='best_rate'").fetchone()
rate = float(r[0]) if r and r[0] else 1_000_000.0
tax = p.sales_tax
reach = g.reach(here, REACH, p.avoid_yellow)
dest = opt("--to", None)
did = g.id_of(dest) if dest else None
direct = reach[did].jumps if did in reach else 0
tail = g.reach(did, REACH * 2, p.avoid_yellow) if did is not None else None

_, buys = load_books(con, set(reach))
opts = []
for s, rt in reach.items():
    sold, net = sell_into_bids(buys.get(tid, {}).get(s, []), qty, tax)
    if not sold:
        continue
    extra = rt.jumps if did is None else max(0, rt.jumps + (tail[s].jumps if s in tail else 99) - direct)
    best_price = buys[tid][s][0][0]
    opts.append({"sys": g.name[s], "jumps": rt.jumps, "extra": extra, "sold": sold, "net": net, "price": best_price,
                 "score": net - extra * MIN_PER_JUMP * rate / 60.0, "how": "dock there"})
try:                                                                    # ranged / region buy orders that reach you: sell from HERE, no travel
    from eve_profit.remoterange import remote_bid
    rb = remote_bid(con, g, tid, qty, here, int(getattr(p, "current_location_id", 0) or 0), tax)
    if rb:
        opts.append({"sys": f"{p.current_system} (to the buy order in {rb['system']}, range {rb['rng']})", "jumps": 0, "extra": 0, "sold": rb["sold"],
                     "net": rb["net"], "price": rb["price"], "score": rb["net"], "how": "from where you are"})
except Exception as e:                                                 # noqa: BLE001
    print("(ranged buy orders not checked:", e, ")")
if not opts:
    sys.exit(f"no buy order for {name} within {REACH} safe jumps (it may only sell as a listing, or only far away)")
now = max((o for o in opts if o["extra"] == 0), key=lambda o: o["net"], default=None)
best = max(opts, key=lambda o: o["score"])
print(f"{qty:,} x {name} from {p.current_system}  (your time: {rate:,.0f} ISK/hr; sales tax {tax:.1%}{'; going to ' + dest if dest else ''})")
if now and now["score"] >= best["score"]:
    print(f"SELL NOW in {now['sys']}: {now['price']:,.0f} best bid, {now['sold']:,} sold = ~{now['net']:,.0f} ISK after tax")
else:
    mins = best["extra"] * MIN_PER_JUMP
    print(("" if now else "(no buyer here or on your way) ") + f"SELL LATER in {best['sys']}: ~{best['net']:,.0f} ISK after tax, {best['extra']} extra jumps ~{mins:.0f} min "
          f"({mins * rate / 60:,.0f} ISK of your time)" + (f"; net gain vs now {best['score'] - now['net']:,.0f}" if now else ""))
base = now["net"] if now else 0.0
print("   markets that pay more than now (net after tax, minus your time for the extra jumps):")
for o in sorted((o for o in opts if o["net"] > base), key=lambda o: -o["score"])[:int(opt("--top", 8))]:
    print(f"      {o['net']:>12,.0f} ISK  bid {o['price']:>11,.0f}  {o['jumps']:>2} jumps, {o['extra']:>2} extra  worth {o['score'] - base:>+12,.0f}  {o['sys']}")
