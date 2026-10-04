import os, sqlite3, tempfile, unittest
from eve_profit import db
from eve_profit.config import Profile
from eve_profit.graph import Graph
from eve_profit.mock import load_mock
from eve_profit.orders import walk_trade
from eve_profit.planner import plan
from eve_profit.sde import import_sde


class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.con = db.connect(os.path.join(self.d, "t.db"))
        load_mock(self.con)

    def test_red_never_in_route(self):
        g = Graph(self.con)
        for s in g.reach(g.id_of("Home"), 6):
            self.assertFalse(g.is_red(s))

    def test_walk_trade_math(self):
        u, c, r = walk_trade([(10, 5, 1), (12, 5, 1)], [(20, 6, 1)], 100, 1e9, 0.0)
        self.assertEqual((u, c, r), (6, 10 * 5 + 12, 120))

    def test_walk_stops_at_unprofitable(self):
        u, *_ = walk_trade([(10, 5, 1), (19.9, 50, 1)], [(20, 100, 1)], 100, 1e9, 0.05)
        self.assertEqual(u, 5)

    def test_plan_sorted_and_positive(self):
        p = Profile(max_jumps=3, cargo_m3=1000, mining_yield_m3_s=0.5,
                    minable_ores=["Veldspar"], min_profit_isk=1)
        o = plan(self.con, p, 50)
        self.assertTrue(o)
        self.assertEqual([x.isk_per_hour for x in o],
                         sorted([x.isk_per_hour for x in o], reverse=True))

    def test_sde_import(self):
        f = os.path.join(self.d, "sde.sqlite")
        s = sqlite3.connect(f)
        s.executescript("""CREATE TABLE mapSolarSystems(solarSystemID,solarSystemName,security,regionID);
        CREATE TABLE mapSolarSystemJumps(fromSolarSystemID,toSolarSystemID);
        CREATE TABLE staStations(stationID,solarSystemID,stationName);
        CREATE TABLE invTypes(typeID,typeName,volume,groupID,published);
        CREATE TABLE invGroups(groupID,categoryID);
        INSERT INTO mapSolarSystems VALUES(1,'A',0.9,5),(2,'B',0.4,5);
        INSERT INTO mapSolarSystemJumps VALUES(1,2);
        INSERT INTO invTypes VALUES(34,'Tritanium',0.01,18,1);
        INSERT INTO invGroups VALUES(18,4);""")
        s.commit()
        self.assertEqual(import_sde(self.con, f), 2)


if __name__ == "__main__":
    unittest.main()
