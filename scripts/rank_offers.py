"""Every open agent offer ranked by net ISK per hour (cash after tax + loot - items to buy, over task time + travel), with LP shown.
python scripts/rank_offers.py [--top 15]
Same math as `next` (nextstep.offers_rows), without the slow market planning."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from eve_profit.db import connect  # noqa: E402
from eve_profit.nextstep import offers_rows  # noqa: E402
from eve_profit.config import Profile  # noqa: E402
from eve_profit.graph import Graph  # noqa: E402

top = int(sys.argv[sys.argv.index("--top") + 1]) if "--top" in sys.argv else 15
con = connect(os.environ.get("EVE_PROFIT_DB") or "E:/EveProfit/eve_profit_dahl.db")
prof = sys.argv[sys.argv.index("--profile") + 1] if "--profile" in sys.argv else "profile_dahl.json"     # the main character
p = Profile.load(os.path.join(ROOT, prof))
rows = offers_rows(con, Graph(con), p)                   # travel counted from where you are now
print(f"from {p.current_system}:")
print(f"{'ISK/hr':>10} {'net ISK':>9} {'min':>4} {'LP':>4}  agent / mission")
for rate, net, minutes, o, tags in rows[:top]:
    name = o["agent"].split(" (")[0]
    m = o.get("mission", "")[:58]
    flag = " [ACCEPTED]" if o.get("accepted") else ""
    print(f"{rate:>10,.0f} {net:>9,.0f} {minutes:>4.0f} {o.get('lp', 0) or 0:>4}  {name}{flag}: {m}")


