import os, tempfile, unittest
from eve_profit import db
from eve_profit.config import Profile
from eve_profit.graph import Graph
from eve_profit.manufacturing import material_qty, build_seconds, buy_cost, find_manufacturing
from eve_profit.mock import load_mock


class T(unittest.TestCase):
    def test_me_rules(self):
        self.assertEqual(material_qty(1000, 1, 10), 900)
        self.assertEqual(material_qty(1, 10, 10), 10)      # never below 1 per run
        self.assertEqual(material_qty(11, 1, 10), 10)      # ceil(9.9)

    def test_time(self):
        p = Profile(industry_level=5, adv_industry_level=0)
        self.assertAlmostEqual(build_seconds(1000, 2, 20, p), 1000 * 2 * 0.8 * 0.8)

    def test_buy_cost(self):
        self.assertEqual(buy_cost([(2, 3, 1), (3, 5, 1)], 5), 2 * 3 + 3 * 2)
        self.assertIsNone(buy_cost([(2, 3, 1)], 4))

    def test_mock_build_is_found_and_profitable(self):
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        p = Profile(max_jumps=3, cargo_m3=100000, wallet_isk=1e9, min_profit_isk=1, min_margin=0)
        con.execute("UPDATE orders SET price=price*1.5 WHERE is_buy=1 AND type_id=90001")
        r = find_manufacturing(con, Graph(con), p)
        self.assertTrue(r and all(o.kind == "build" and o.profit_isk > 0 for o in r))
        self.assertGreater(r[0].detail["job_hours"], 0)


if __name__ == "__main__":
    unittest.main()
