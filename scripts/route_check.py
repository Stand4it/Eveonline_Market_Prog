"""Is a place ON THE WAY? python scripts/route_check.py FROM TO PLACE  -> the safe route FROM>TO, and whether PLACE is on it (else the extra jumps for a detour).
Uses the Stand4it Dahl database (override with EVE_PROFIT_DB)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from eve_profit.db import connect  # noqa: E402
from eve_profit.graph import Graph  # noqa: E402

a, b, c = sys.argv[1:4]
con = connect(os.environ.get("EVE_PROFIT_DB") or "E:/EveProfit/eve_profit_dahl.db")
g = Graph(con)


def route(x, y):
    r = g.route(g.id_of(x), g.id_of(y), 60, True)
    return [g.name[s] for s in r.path] if r else None


direct, via1, via2 = route(a, b), route(a, c), route(c, b)
print(f"{a} > {b}: {' > '.join(direct)}  ({len(direct) - 1} jumps)")
if c in direct:
    print(f"{c} IS ON THE WAY: no detour.")
else:
    extra = (len(via1) - 1) + (len(via2) - 1) - (len(direct) - 1)
    print(f"{c} is NOT on the way: {a} > {c} is {len(via1) - 1} jumps, {c} > {b} is {len(via2) - 1}; the detour adds {extra} jumps (about {extra * 3} min).")
