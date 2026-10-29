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
        goals = {"gun": {"tool": "gun", "skills": [], "hull": [], "items": [], "goals": [{"name": "x", "isk": 600000.0, "minutes": 60.0, "modeled": True}]}}
        with mock.patch.object(preptree, "goals", return_value=goals), mock.patch.object(preptree, "_combat_items", return_value=[("Widget", 1)]), \
                mock.patch("eve_profit.skills.have", return_value={}):
            c = preptree.chains(con, g, p, 0.0, haul=False)[0]
        self.assertAlmostEqual(c["cash"], 100000.0)
        self.assertLess(c["chain_min"], 10000.0)                           # (600k - 100k) / (60 + prep minutes)
        self.assertGreater(c["chain_min"], 7000.0)

    def test_skill_training_ranks_a_chain_lower_but_queueing_is_its_first_step(self):
        con, g, p = self._world(100000.0)
        goals = {"ice_mining": {"tool": None, "skills": [("Ice Harvesting", 1)], "hull": [], "items": [],
                                "goals": [{"name": "Ice", "isk": 600000.0, "minutes": 60.0, "modeled": False}]}}
        q = {"ice harvesting": 0}
        with mock.patch.object(preptree, "goals", return_value=goals), mock.patch.object(preptree, "_training", return_value=(24.0, [], {
                "how": "do", "item": "skills", "qty": 1, "cash": 0.0, "minutes": 1.0, "cost": 0.0, "children": [], "text": "QUEUE", "step": "STEP: QUEUE"})), \
                mock.patch("eve_profit.catalog.skill_levels", return_value=q):
            c = preptree.chains(con, g, p, 0.0, haul=False)[0]
        self.assertAlmostEqual(c["rank_min"], c["chain_min"] / 2.0)       # 24 h of training halves the rank
        self.assertEqual(c["steps"][0]["item"], "skills")

    def test_missing_book_is_bought_before_the_queue_step(self):
        """owner 2026-10-28: Planetology needs Remote Sensing; neither book owned -> both are buy steps and the queue step comes last."""
        con, g, p = self._world(100000.0)
        goals = {"pi": {"tool": None, "skills": [("Planetology", 1)], "hull": [], "items": [],
                        "goals": [{"name": "PI", "isk": 600000.0, "minutes": 60.0, "modeled": False}]}}
        node = {"how": "do", "item": "skills", "qty": 1, "cash": 0.0, "minutes": 1.0, "cost": 0.0, "children": [], "text": "QUEUE",
                "step": "STEP: QUEUE\n   Character sheet > Skills"}
        bought = []
        def fake_source(ctx, it, q):
            bought.append(it)
            return {"how": "buy", "item": it, "qty": q, "cash": 1.0, "minutes": 1.0, "cost": 1.0, "children": [], "step": f"STEP: BUY {it}"}
        with mock.patch.object(preptree, "goals", return_value=goals), \
                mock.patch.object(preptree, "_training", return_value=(1.0, ["Remote Sensing", "Planetology"], node)), \
                mock.patch.object(preptree, "source", side_effect=fake_source), \
                mock.patch("eve_profit.catalog.skill_levels", return_value={}):
            c = preptree._chains_calc(con, g, p, 0.0, haul=False)[0]
        self.assertEqual(sorted(bought), ["Planetology", "Remote Sensing"])
        self.assertEqual(c["steps"][-1]["item"], "skills")
        self.assertIn("FIRST inject the books", c["steps"][-1]["step"])

    def test_a_prep_buy_here_is_scheduled_even_when_its_chain_ranks_low(self):
        """owner 2026-10-29: no travel = nearly free: a buy whose cheapest place is this system comes first, whatever the chain's rank."""
        chain = {"group": "scanning", "goals": [], "chain_min": 10.0, "rank_min": 10.0, "cash": 18000.0, "unknown": [],
                 "steps": [{"how": "buy", "item": "Core Probe Launcher I", "qty": 1, "cash": 18000.0, "jumps": 0, "src": {}}]}
        con, g, p = self._world(1000000.0)
        with mock.patch.object(preptree, "chains", return_value=[chain]),                 mock.patch.object(preptree, "first_step", return_value="STEP: BUY 1 x Core Probe Launcher I here"):
            out = preptree.candidates(con, g, p, 5000000.0, None)
        self.assertEqual(out[0][1], "prep: Core Probe Launcher I")
        self.assertGreater(out[0][0], 5000000.0)
        far = dict(chain, steps=[dict(chain["steps"][0], jumps=3)])
        with mock.patch.object(preptree, "chains", return_value=[far]),                 mock.patch.object(preptree, "first_step", return_value="STEP: FLY"):
            self.assertEqual(preptree.candidates(con, g, p, 5000000.0, None), [])


if __name__ == "__main__":
    unittest.main()
