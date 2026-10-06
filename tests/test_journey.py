import os, tempfile, unittest
from eve_profit import db
from eve_profit.config import Profile
from eve_profit.graph import Graph
from eve_profit.journey import format_journey, plan_journey
from eve_profit.mock import load_mock


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


def prof(**kw):
    d = dict(max_jumps=3, cargo_m3=100000, wallet_isk=1e9, min_profit_isk=1, current_location_id=60000001, secs_per_jump=45)
    d.update(kw)
    return Profile(**d)


class JourneyTests(unittest.TestCase):
    def test_stock_is_carried_to_the_better_market_and_trades_are_added(self):
        con, g, path = world()
        order(con, 1, 34, 1, 5.0, 1); order(con, 2, 34, path[-1], 8.0, 1)           # stock sells better at the end
        con.execute("INSERT INTO inventory VALUES(34,1,1000)")
        order(con, 3, 35, path[1], 10.0, 0); order(con, 4, 35, path[-1], 20.0, 1)    # buy mid-route, sell at the end
        res = plan_journey(con, g, prof(), g.name[path[-1]], detour=0)
        self.assertGreater(res["stock_net"], 0)
        self.assertGreater(res["trade_profit"], 0)
        self.assertGreater(res["total"], res["trade_profit"])
        txt = format_journey(res)
        self.assertIn("pick up", txt)
        self.assertIn("buy", txt)
        self.assertIn("TOTAL", txt)

    def test_never_sells_stock_below_what_you_paid(self):
        con, g, path = world()
        order(con, 1, 34, path[-1], 5.0, 1)
        con.execute("INSERT INTO inventory VALUES(34,1,1000)")
        con.execute("INSERT INTO transactions(transaction_id,type_id,quantity,unit_price,is_buy,location_id,date) "
                    "VALUES(1,34,1000,50.0,1,60000001,'')")
        res = plan_journey(con, g, prof(), g.name[path[-1]], detour=0)
        self.assertEqual(res["stock_net"], 0)
        self.assertEqual(len(res["held"]), 1)

    def test_hold_limits_what_is_carried(self):
        con, g, path = world()
        order(con, 1, 34, path[-1], 8.0, 1)
        con.execute("INSERT INTO inventory VALUES(34,1,1000000)")
        res = plan_journey(con, g, prof(cargo_m3=100), g.name[path[-1]], detour=0)
        self.assertLessEqual(res["used_m3"], 100.0001)
        self.assertTrue(res["left_behind"] or res["stock_net"] < 8.0 * 1000000)


if __name__ == "__main__":
    unittest.main()
