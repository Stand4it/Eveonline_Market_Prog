import os
import tempfile
import unittest
from unittest import mock

from eve_profit import db, preptree
from eve_profit.config import Profile
from eve_profit.graph import Graph
from eve_profit.mock import load_mock


class PrepTreeTests(unittest.TestCase):
    def _world(self, widget_price, bp_price=None, mat_price=10.0, bid=None):
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        con.execute("INSERT OR REPLACE INTO types(type_id,name,volume,group_id) VALUES(880001,'Widget',5,1)")
        con.execute("INSERT OR REPLACE INTO types(type_id,name,volume,group_id) VALUES(880002,'Widget Blueprint',0.01,2)")
        con.execute("INSERT OR REPLACE INTO types(type_id,name,volume,group_id) VALUES(880003,'Zydrine Bit',1,3)")
        con.execute("INSERT INTO orders VALUES(990001,880001,60000001,1,10000001,0,?,50,1,'',1)", (widget_price,))
        con.execute("INSERT INTO orders VALUES(990002,880003,60000001,1,10000001,0,?,1000000,1,'',1)", (mat_price,))
        if bp_price is not None:
            con.execute("INSERT INTO orders VALUES(990003,880002,60000001,1,10000001,0,?,5,1,'',1)", (bp_price,))
        if bid is not None:
            con.execute("INSERT INTO orders VALUES(990004,880001,60000001,1,10000001,1,?,50,1,'',1)", (bid,))
        con.execute("INSERT INTO bp_materials VALUES(880002,880003,3000)")
        con.execute("INSERT INTO bp_products VALUES(880002,880001,1,600)")
        g = Graph(con)
        p = Profile(current_system="Home", wallet_isk=1e8, current_location_id=60000001)
        return con, g, p

    def _source(self, con, g, p, qty=1, rate_min=1000.0):
        with mock.patch("eve_profit.skills.have", return_value={}):
            return preptree.source(preptree.Ctx(con, g, p, rate_min), "Widget", qty)

    def test_buy_when_no_blueprint_is_for_sale(self):
        n = self._source(*self._world(100000.0))
        self.assertEqual(n["how"], "buy")

    def test_build_with_a_bought_blueprint_when_cheaper(self):
        n = self._source(*self._world(900000.0, bp_price=50000.0))
        self.assertEqual(n["how"], "build")
        self.assertEqual([k["how"] for k in n["children"]][0], "buy")     # the blueprint is bought first
        self.assertIn("Widget Blueprint", [k["item"] for k in n["children"]])

    def test_dear_blueprint_loses_to_buying(self):
        n = self._source(*self._world(100000.0, bp_price=5_000_000.0))
        self.assertEqual(n["how"], "buy")
        self.assertIn("build", n.get("beat", ""))

    def test_batch_built_and_rest_sold_when_it_pays(self):
        n = self._source(*self._world(900000.0, bp_price=50000.0, bid=800000.0))
        self.assertEqual(n["how"], "build")
        self.assertGreater(n["runs"], 1)                                   # make one for yourself, sell the others
        self.assertTrue(any("sell the other" in a for a in n["after"]))

    def test_held_item_is_free(self):
        con, g, p = self._world(100000.0)
        with mock.patch("eve_profit.acquire.held", return_value=5):
            n = self._source(con, g, p)
        self.assertEqual((n["how"], n["cost"]), ("held", 0.0))

    def test_leaves_put_materials_before_the_build(self):
        n = self._source(*self._world(900000.0, bp_price=50000.0))
        order = [s["how"] for s in preptree.leaves(n)]
        self.assertEqual(order[-1], "build")

    def test_mine_beats_buying_a_dear_mineral(self):
        con, g, p = self._world(100000.0, mat_price=1000.0)
        ores = {"fee_per_unit": 0.0, "ores": {"Zydrine Rock": {"per_unit": {"Zydrine Bit": 1.0}}}}
        with mock.patch("eve_profit.reprocess.load", return_value=ores), mock.patch.object(preptree, "mining_tool_missing", return_value=[]):
            n = preptree.source(preptree.Ctx(con, g, p, 10.0), "Zydrine Bit", 3000, depth=1, raw_only=True)
        self.assertEqual(n["how"], "mine")

    def test_chain_rate_counts_prep_cash_and_minutes(self):
        con, g, p = self._world(100000.0)
        goals = {"gun": [{"name": "x", "isk": 600000.0, "minutes": 60.0, "modeled": True}]}
        with mock.patch.object(preptree, "goals", return_value=goals), mock.patch.object(preptree, "_combat_items", return_value=[("Widget", 1)]), \
                mock.patch("eve_profit.skills.have", return_value={}):
            c = preptree.chains(con, g, p, 0.0, haul=False)[0]
        self.assertAlmostEqual(c["cash"], 100000.0)
        self.assertLess(c["chain_min"], 10000.0)                           # (600k - 100k) / (60 + prep minutes)
        self.assertGreater(c["chain_min"], 7000.0)


if __name__ == "__main__":
    unittest.main()
