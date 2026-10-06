import os, tempfile, unittest
from eve_profit import db
from eve_profit.compare import compare, format_compare
from eve_profit.config import Profile
from eve_profit.graph import Graph
from eve_profit.mock import load_mock


class FakeESI:
    def __init__(self, vol):
        self.vol = vol

    def get(self, path, **kw):
        return [{"volume": self.vol}] * 30, 1


def world():
    con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
    load_mock(con)
    g = Graph(con)
    con.execute("DELETE FROM inventory"); con.execute("DELETE FROM orders WHERE type_id IN (34,35,36)")
    r = g.reach(1, 3)
    path = g.route(1, [s for s, x in r.items() if x.jumps == 2][0]).path
    return con, g, path


def order(con, oid, tid, system, price, buy, qty=10**9):
    con.execute("INSERT INTO orders VALUES(?,?,?,?,10000001,?,?,?,1,'',1)", (oid, tid, 60000000 + system, system, buy, price, qty))


class CompareTests(unittest.TestCase):
    def setup(self):
        con, g, path = world()
        order(con, 1, 34, 1, 5.0, 1)                       # bid here
        order(con, 2, 34, 1, 12.0, 0)                      # ask here: listing would pay 2.4x the bid
        order(con, 3, 34, path[-1], 9.0, 1)                # better bid at the destination
        con.execute("INSERT INTO inventory VALUES(34,1,100000)")
        p = Profile(max_jumps=3, cargo_m3=100000, wallet_isk=1e9, min_profit_isk=1, current_location_id=60000001, secs_per_jump=45)
        return con, g, path, p

    def test_fast_market_lists_here_and_slow_market_does_not(self):
        con, g, path, p = self.setup()
        fast = compare(con, g, p, FakeESI(100000), g.name[path[-1]], detour=0)
        self.assertEqual(len(fast["fast"]), 1)
        slow = compare(con, g, p, FakeESI(1), g.name[path[-1]], detour=0)
        self.assertEqual(len(slow["fast"]), 0)
        names = [r["name"][0] for r in fast["rows"]]
        self.assertEqual(names, ["A", "B", "C", "D"])
        txt = format_compare(fast)
        self.assertIn("BEST", txt)
        self.assertIn("extra ISK per extra min", txt)

    def test_instant_sale_here_is_the_baseline(self):
        con, g, path, p = self.setup()
        r = compare(con, g, p, FakeESI(100000), g.name[path[-1]], detour=0)
        a = r["rows"][0]
        self.assertAlmostEqual(a["total"], 100000 * 5.0 * (1 - p.sales_tax), places=2)
        self.assertIsNone(a["marginal"])


if __name__ == "__main__":
    unittest.main()
