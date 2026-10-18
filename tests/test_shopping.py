import os
import tempfile
import unittest

from eve_profit import db, shopping
from eve_profit.config import Profile
from eve_profit.graph import Graph
from eve_profit.mock import load_mock

os.environ["EVE_NO_LIVE"] = "1"


class ShoppingTests(unittest.TestCase):
    def _world(self):
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        con.execute("INSERT OR REPLACE INTO types(type_id,name,volume,group_id) VALUES(880001,'Incursus',2500,25)")
        con.execute("INSERT INTO orders VALUES(990001,880001,60000001,1,10000001,0,100000.0,5,1,'',1)")
        return con

    def test_wish_when_no_hull_and_step_when_this_is_the_cheapest_place(self):
        con = self._world()
        g = Graph(con)
        p = Profile(current_system="Home", wallet_isk=1e7, current_location_id=60000001)
        p.ship_name = "Capsule - X"
        items = [w["item"] for w in shopping.wishes(con, p)]
        self.assertIn("Incursus", items)
        out = shopping.candidates(con, g, p, 500_000.0, lambda *a, **k: "")
        self.assertTrue(out and out[0][2].startswith("STEP: ACQUIRE 1 x Incursus"))
        self.assertGreater(out[0][0], 500_000.0)                       # ranks just above the best step

    def test_no_step_when_the_item_is_not_sold_here_and_lines_name_the_place(self):
        con = self._world()
        g = Graph(con)
        p = Profile(current_system="Home", wallet_isk=1e7, current_location_id=60000001)
        p.ship_name = "Capsule - X"
        con.execute("DELETE FROM orders WHERE type_id=880001")
        self.assertEqual(shopping.candidates(con, g, p, 500_000.0, lambda *a, **k: ""), [])
        self.assertIn("Incursus", shopping.lines(con, g, p))

    def test_too_expensive_for_the_wallet_share_is_not_a_step(self):
        con = self._world()
        g = Graph(con)
        p = Profile(current_system="Home", wallet_isk=500_000.0, current_location_id=60000001)      # 100k is 20% of this wallet
        p.ship_name = "Capsule - X"
        self.assertEqual(shopping.candidates(con, g, p, 500_000.0, lambda *a, **k: ""), [])


if __name__ == "__main__":
    unittest.main()
