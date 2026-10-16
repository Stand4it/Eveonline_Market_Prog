import os
import tempfile
import unittest

from eve_profit import acquire, db
from eve_profit.config import Profile
from eve_profit.graph import Graph
from eve_profit.mock import load_mock


class AcquireTests(unittest.TestCase):
    def _world(self):
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        con.execute("INSERT OR REPLACE INTO types(type_id,name,volume,group_id) VALUES(880001,'Widget',5,1)")
        con.execute("INSERT OR REPLACE INTO types(type_id,name,volume,group_id) VALUES(880002,'Widget Blueprint',0.01,2)")
        con.execute("INSERT OR REPLACE INTO types(type_id,name,volume,group_id) VALUES(880003,'Zydrine Bit',1,3)")
        return con

    def test_buy_beats_a_dearer_build(self):
        con = self._world()
        con.execute("INSERT INTO orders VALUES(990001,880001,60000001,1,10000001,0,100000.0,5,1,'',1)")
        con.execute("INSERT INTO orders VALUES(990002,880003,60000001,1,10000001,0,100.0,100000,1,'',1)")
        con.execute("INSERT INTO bp_materials VALUES(880002,880003,3000)")
        g = Graph(con)
        p = Profile(current_system="Home", wallet_isk=1e7, current_location_id=60000001)
        w = acquire.best_way(con, g, p, "Widget", 1)
        self.assertEqual(w["mode"], "buy")
        self.assertAlmostEqual(w["buy"]["price"], 100000.0)
        self.assertIsNotNone(w["build"])
        self.assertGreater(w["build"]["cost"], w["buy"]["cost"])

    def test_build_wins_when_materials_are_cheap(self):
        con = self._world()
        con.execute("INSERT INTO orders VALUES(990001,880001,60000001,1,10000001,0,400000.0,5,1,'',1)")
        con.execute("INSERT INTO orders VALUES(990002,880003,60000001,1,10000001,0,10.0,100000,1,'',1)")
        con.execute("INSERT INTO bp_materials VALUES(880002,880003,3000)")
        g = Graph(con)
        p = Profile(current_system="Home", wallet_isk=1e7, current_location_id=60000001)
        self.assertEqual(acquire.best_way(con, g, p, "Widget", 1)["mode"], "build")

    def test_a_purchase_is_remembered_for_two_hours(self):
        con = self._world()
        self.assertEqual(acquire.held(con, "Widget"), 0)
        acquire.confirm(con, "Widget", 1)
        self.assertEqual(acquire.held(con, "Widget"), 1)
        g = Graph(con)
        p = Profile(current_system="Home", wallet_isk=1e7)
        self.assertEqual(acquire.best_way(con, g, p, "Widget", 1)["mode"], "held")


if __name__ == "__main__":
    unittest.main()
