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

    def test_client_id_validation_and_priority(self):
        from eve_profit.cli import resolve_client_id
        good = "1bcbf467858d46c29b98c19f5cf383c7"
        old = os.getcwd()
        os.chdir(self.d)
        try:
            os.environ["EVE_CLIENT_ID"] = "paste-client-id-here"           # stale placeholder in env
            self.assertEqual(resolve_client_id(good), good)                # explicit wins
            with self.assertRaises(SystemExit):
                resolve_client_id("")                                      # placeholder alone is rejected
            open("client_id.txt", "w").write(good + "\n")
            self.assertEqual(resolve_client_id(""), good)                  # file beats bad env
        finally:
            os.environ.pop("EVE_CLIENT_ID", None)
            os.chdir(old)

    def test_regions_near(self):
        from eve_profit.cli import regions_near
        self.assertEqual(regions_near(self.con, Profile()), [10000001])

    def test_unknown_system_is_a_clean_error(self):
        from eve_profit.cli import main
        pf = os.path.join(self.d, "p.json")
        Profile(current_system="Nowhere").save(pf)
        with self.assertRaises(SystemExit) as cm:
            main(["scan", "--db", os.path.join(self.d, "t.db"), "--profile", pf])
        self.assertIn("not found", str(cm.exception))

    def test_sde_extract_plain_and_bz2(self):
        import bz2
        from eve_profit.sde import extract
        plain = os.path.join(self.d, "a.sqlite")
        open(plain, "wb").write(b"x")
        self.assertEqual(extract(plain, os.path.join(self.d, "out.sqlite")), plain)
        z = os.path.join(self.d, "b.sqlite.bz2")
        open(z, "wb").write(bz2.compress(b"hello"))
        out = os.path.join(self.d, "o2.sqlite")
        self.assertEqual(open(extract(z, out), "rb").read(), b"hello")

    def test_sde_import(self):
        f = os.path.join(self.d, "sde.sqlite")
        s = sqlite3.connect(f)
        s.executescript("""CREATE TABLE mapSolarSystems(solarSystemID,solarSystemName,security,regionID);
        CREATE TABLE mapSolarSystemJumps(fromSolarSystemID,toSolarSystemID);
        CREATE TABLE staStations(stationID,solarSystemID,stationName,corporationID);
        CREATE TABLE agtAgents(agentID,corporationID,locationID,level,quality,agentTypeID);
        CREATE TABLE crpNPCCorporations(corporationID,factionID);
        INSERT INTO staStations VALUES(60,1,'S1',1000);
        INSERT INTO agtAgents VALUES(7,1000,60,3,10,2),(8,1000,60,1,0,5);
        INSERT INTO crpNPCCorporations VALUES(1000,500);
        CREATE TABLE invTypes(typeID,typeName,volume,groupID,published);
        CREATE TABLE invGroups(groupID,categoryID);
        INSERT INTO mapSolarSystems VALUES(1,'A',0.9,5),(2,'B',0.4,5);
        INSERT INTO mapSolarSystemJumps VALUES(1,2);
        INSERT INTO invTypes VALUES(34,'Tritanium',0.01,18,1);
        INSERT INTO invGroups VALUES(18,4);""")
        s.commit()
        self.assertEqual(import_sde(self.con, f), 2)
        self.assertEqual([tuple(r) for r in self.con.execute("SELECT agent_id,system_id,level FROM agents")],
                         [(7, 1, 3)])                       # only basic mission agents (type 2)
        self.assertEqual(self.con.execute("SELECT faction_id FROM corp_faction").fetchone()[0], 500)


if __name__ == "__main__":
    unittest.main()


class LiquidationTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.con = db.connect(os.path.join(self.d, "t.db"))
        load_mock(self.con)
        self.con.execute("DELETE FROM inventory")

    def _find(self, **kw):
        from eve_profit.trade import find_liquidations
        p = Profile(max_jumps=3, min_profit_isk=1, **kw)
        return find_liquidations(self.con, Graph(self.con), p)

    def test_cargo_cap_and_trip_to_stock_are_counted(self):
        g = Graph(self.con)
        far = next(s for s in g.reach(1, 2) if g.reach(1, 2)[s].jumps == 2)
        # 1,000,000 Tritanium (0.01 m3 = 10,000 m3 total) held 2 jumps away
        self.con.execute("INSERT INTO inventory VALUES(34,?,1000000)", (far,))
        r = self._find(cargo_m3=5000)
        self.assertTrue(r)
        o = r[0]
        self.assertLessEqual(o.detail["units"], 500000)            # 5,000 m3 / 0.01
        self.assertGreaterEqual(o.jumps, 2 + 1)                    # trip to the stock + trip to the buyer
        self.assertEqual(o.waypoints[:2], g.route(1, far).path[1:])

    def test_stock_where_you_stand_has_no_pickup_leg(self):
        self.con.execute("INSERT INTO inventory VALUES(34,1,100000)")
        o = self._find(cargo_m3=5000)[0]
        self.assertEqual(o.route.split(" | ")[0], "Home")
