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


class TestBlockedGoals(unittest.TestCase):
    def test_blocked_goals_listed_by_isk_per_minute(self):
        from unittest import mock
        from eve_profit import dailygoals as dg, shopping
        blocked = lambda goal: {"goal": goal, "ok": False, "why_not": "x", "minutes": 0, "cash": 0}
        with mock.patch.object(dg, "scan_option", return_value=blocked("Scan 5 Signatures")), mock.patch.object(dg, "mine_option", return_value=blocked("Mine 2000 units of Ore")), \
                mock.patch.object(dg, "today_goals", return_value=None):
            out = shopping.blocked_goals(None, None, None)
        self.assertEqual([b["goal"] for b in out], ["Mine 2000 units of Ore", "Scan 5 Signatures"])        # 15 min beats 35 min
        self.assertGreater(out[0]["per_min"], out[1]["per_min"])


if __name__ == "__main__":
    unittest.main()


class ToolsTests(unittest.TestCase):
    def test_fit_plan_uses_slots(self):
        from eve_profit import tools
        self.assertEqual(tools.fit_plan({"high": 3, "turret": 2, "launcher": 1}), [("scanning", 1), ("salvaging", 1), ("mining", 1)])
        self.assertEqual([t for t, _ in tools.fit_plan({"high": 6, "turret": 4, "launcher": 2})], ["scanning", "salvaging", "mining"])
        self.assertEqual(tools.fit_plan({"high": 1, "turret": 1, "launcher": 0}), [("salvaging", 1)])
        self.assertEqual(tools.fit_plan(None), [])

    def test_tool_wishes_follow_the_best_hull(self):
        from eve_profit import tools
        con = ShoppingTests()._world()
        con.execute("INSERT INTO meta VALUES('ship_slots', ?)", ('{"1": {"high": 3, "mid": 2, "low": 3, "turret": 2, "launcher": 1}}',))
        con.execute("INSERT OR REPLACE INTO types(type_id,name,volume,group_id) VALUES(1,'Frigate X',2500,25)")
        con.execute("INSERT INTO my_ships(item_id,type_id,system_id,location_id) VALUES(5,1,30000001,60000001)")
        p = Profile(current_system="Home", wallet_isk=1e7, current_location_id=60000001)
        p.ship_name = "Capsule - X"
        p.ship_type_id = 0
        items = {w["item"] for w in shopping.wishes(con, p)}
        self.assertTrue({"Core Probe Launcher I", "Salvager I", "Miner I"} <= items, items)
        self.assertEqual(tools.carrier(con, p)[0], "Frigate X")


class ShipsTests(unittest.TestCase):
    def test_upgrade_picks_the_hull_with_more_tools_per_isk(self):
        import json
        from eve_profit import ships
        con = ShoppingTests()._world()
        con.execute("INSERT OR REPLACE INTO types(type_id,name,volume,group_id,category_id) VALUES(880002,'Big Frigate',2500,25,6)")
        con.execute("INSERT INTO orders VALUES(990002,880002,60000001,1,10000001,0,300000.0,5,1,'',1)")
        cat = {"880002": {"name": "Big Frigate", "group": "Frigate", "slots": {"high": 4, "mid": 3, "low": 3, "turret": 3, "launcher": 2}},
               "880001": {"name": "Incursus", "group": "Frigate", "slots": {"high": 1, "mid": 3, "low": 3, "turret": 1, "launcher": 0}}}
        con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (ships.KEY, json.dumps(cat)))
        g = Graph(con)
        p = Profile(current_system="Home", wallet_isk=1e7, current_location_id=60000001)
        p.ship_name = "Capsule - X"
        up = ships.upgrade(con, g, p)
        self.assertEqual(up["item"], "Big Frigate")
        self.assertIn("carries", up["why"])
        self.assertIn("Big Frigate", [w["item"] for w in shopping.wishes(con, p, g)])
        self.assertIn("Big Frigate", ships.report(con, g, p))


class BuildOnlyWithBlueprint(unittest.TestCase):
    def test_no_blueprint_means_buy(self):
        con = ShoppingTests()._world()
        con.execute("INSERT OR REPLACE INTO types(type_id,name,volume,group_id) VALUES(880003,'Incursus Blueprint',0.01,2)")
        con.execute("INSERT OR REPLACE INTO types(type_id,name,volume,group_id) VALUES(880004,'Tritanium',0.01,3)")
        con.execute("INSERT INTO orders VALUES(990004,880004,60000001,1,10000001,0,1.0,500000,1,'',1)")
        con.execute("INSERT INTO bp_materials VALUES(880003,880004,13333)")             # building looks far cheaper than the 100,000 market price
        g = Graph(con)
        p = Profile(current_system="Home", wallet_isk=1e7, current_location_id=60000001)
        w = {"item": "Incursus", "qty": 1, "why": "x"}
        self.assertFalse(shopping._owns_blueprint(con, "Incursus"))
        self.assertEqual(shopping._way(con, g, p, w)["mode"], "buy")
        con.execute("INSERT INTO my_blueprints VALUES(880003,0,0,-1)")
        self.assertTrue(shopping._owns_blueprint(con, "Incursus"))
        self.assertEqual(shopping._way(con, g, p, w)["mode"], "build")


class SourceRanking(unittest.TestCase):
    def test_a_near_dearer_listing_beats_a_far_bargain_even_past_the_twelve_cheapest(self):
        from eve_profit import acquire
        con = ShoppingTests()._world()
        con.execute("DELETE FROM orders WHERE type_id=880001")
        g = Graph(con)
        p = Profile(current_system="Home", wallet_isk=1e7, current_location_id=60000001)
        far = g.id_of("Sys28")                                        # 6 jumps away in the mock map
        home = g.id_of("Home")
        for i in range(14):                                           # 14 cheap listings far away fill the old top-12 cut
            con.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?)", (991000 + i, 880001, 61000000 + i, far, 10000001, 0, 1000.0 + i, 5, 1, "", 1))
        con.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?)", (992000, 880001, 60000001, home, 10000001, 0, 100000.0, 5, 1, "", 1))
        best = acquire.sources(con, g, p, "Incursus", 1)[0]
        self.assertEqual(best["system"], "Home")                      # 100,000 here beats 1,000 six jumps away (6 x 50,000 for the trip)

    def test_carrier_prefers_the_hull_that_carries_more(self):
        from eve_profit import tools
        con = ShoppingTests()._world()
        con.execute("INSERT OR REPLACE INTO types(type_id,name,volume,group_id) VALUES(1,'Imicusish',2500,25)")
        con.execute("INSERT OR REPLACE INTO types(type_id,name,volume,group_id) VALUES(2,'Venturish',2500,25)")
        con.execute("INSERT INTO meta VALUES('ship_slots', ?)", ('{"1": {"high": 3, "turret": 1, "launcher": 0}, "2": {"high": 3, "turret": 2, "launcher": 0}}',))
        con.execute("INSERT INTO my_ships(item_id,type_id,system_id,location_id) VALUES(5,1,30000001,60000001)")
        con.execute("INSERT INTO my_ships(item_id,type_id,system_id,location_id) VALUES(6,2,30000001,60000001)")
        p = Profile(current_system="Home", wallet_isk=1e7)
        p.ship_name = "Capsule - X"
        p.ship_type_id = 0
        self.assertEqual(tools.carrier(con, p)[0], "Venturish")
