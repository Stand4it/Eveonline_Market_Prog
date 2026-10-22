"""Cheapest place to BUY an item counting the trip (price x qty + jumps x the value of a jump), from where you are or --from SYSTEM.
python scripts/where_buy.py "Small Armor Repairer I" [qty] [--from Halaima] [--top 6]"""
import dataclasses
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from eve_profit import acquire  # noqa: E402
from eve_profit.config import Profile  # noqa: E402
from eve_profit.db import connect  # noqa: E402
from eve_profit.graph import Graph  # noqa: E402

args = [a for a in sys.argv[1:]]
opt = lambda k, d: args[args.index(k) + 1] if k in args else d  # noqa: E731
pos = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or not args[i - 1].startswith("--"))]
item, qty = pos[0], int(pos[1]) if len(pos) > 1 else 1
con = connect(os.environ.get("EVE_PROFIT_DB") or "E:/EveProfit/eve_profit_dahl.db")
p = Profile.load(os.path.join(ROOT, "profile_dahl.json"))
p = dataclasses.replace(p, current_system=opt("--from", p.current_system))
rows = acquire.sources(con, Graph(con), p, item, qty, max_jumps=14)
print(f"{qty} x {item} from {p.current_system} (a jump counted at {acquire.JUMP_VALUE_ISK:,.0f} ISK):")
for r in rows[:int(opt("--top", 6))]:
    print(f"   {r['price']:>12,.0f} each  {r['jumps']:>2} jumps  total ~{r['cost']:>12,.0f}  {r['system']}  {r['station'][:60]}")
