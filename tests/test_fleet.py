import os, tempfile, unittest
from eve_profit import db
from eve_profit.combat import seed_defaults
from eve_profit.config import Profile
from eve_profit.fleet import describe_fleet, parked_ships, swap_opportunities, variant_profile
from eve_profit.graph import Graph
from eve_profit.mock import load_mock
from eve_profit.planner import FINDERS, plan


def setup():
    con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
    load_mock(con)
    seed_defaults(con)
    con.execute("UPDATE types SET capacity=50000 WHERE type_id=90001")       # pretend Mock Widget is a big hauler hull
    g = Graph(con)
    far = [s for s, r in g.reach(1, 2).items() if r.jumps == 2][0]
    con.execute("INSERT INTO my_ships VALUES(1001,90001,?,60000000)", (far,))
    return con, g, far


class T(unittest.TestCase):
    def test_parked_and_variant(self):
        con, g, far = setup()
        s = parked_ships(con)
        self.assertEqual((s[0]["name"], s[0]["capacity"]), ("Mock Widget", 50000))
        p2 = variant_profile(Profile(combat_dps=999, cargo_m3=100), s[0], g.name[far])
        self.assertEqual((p2.cargo_m3, p2.combat_dps, p2.current_system), (50000, 0.0, g.name[far]))   # no stats -> no combat

    def test_swap_charges_trip_and_prefixes(self):
        con, g, far = setup()
        p = Profile(max_jumps=2, cargo_m3=500, wallet_isk=1e9, min_profit_isk=1)
        r = swap_opportunities(con, g, p, FINDERS)
        self.assertTrue(r)
        o = r[0]
        self.assertIn("[swap to Mock Widget", o.description)
        self.assertGreaterEqual(o.jumps, 2)
        self.assertEqual(o.waypoints[:2], g.route(1, far).path[1:])
        self.assertFalse([w for w in o.waypoints if g.is_red(w)])

    def test_swap_combat_needs_stats(self):
        con, g, far = setup()
        p = Profile(max_jumps=3, cargo_m3=500, wallet_isk=1e9, min_profit_isk=1)
        every = dict(per_variant=10000)                      # don't let trades crowd combat out of the top 5
        self.assertFalse([o for o in swap_opportunities(con, g, p, FINDERS, **every) if o.kind.startswith("combat")])
        p.ships = {"Mock Widget": {"combat_dps": 700, "ship_ehp": 200000, "ship_tank_dps": 400}}
        self.assertTrue([o for o in swap_opportunities(con, g, p, FINDERS, **every) if o.kind.startswith("combat")])

    def test_planner_includes_swaps_and_can_disable(self):
        con, g, far = setup()
        p = Profile(max_jumps=2, cargo_m3=500, wallet_isk=1e9, min_profit_isk=1)
        self.assertTrue([o for o in plan(con, p, 100000, False) if "[swap to" in o.description])
        p.consider_ship_swaps = False
        self.assertFalse([o for o in plan(con, p, 100000, False) if "[swap to" in o.description])

    def test_describe_fleet(self):
        con, g, far = setup()
        txt = describe_fleet(con, g, Profile())
        self.assertIn("Mock Widget", txt)
        self.assertIn("2 jumps", txt)


if __name__ == "__main__":
    unittest.main()


class StockTests(unittest.TestCase):
    def test_stock_report_values_and_flags_unpriced(self):
        from eve_profit.stock import stock_report
        con, g, far = setup()
        con.execute("DELETE FROM inventory")
        con.execute("INSERT INTO inventory VALUES(34,1,1000)")           # Tritanium: has buyers nearby
        con.execute("INSERT INTO types(type_id,name,volume) VALUES(77777,'Odd Skin',0.1)")
        con.execute("INSERT INTO inventory VALUES(77777,1,5)")           # no orders anywhere
        txt = stock_report(con, g, Profile(max_jumps=2))
        self.assertIn("Tritanium", txt)
        self.assertIn("Odd Skin x5", txt)
        self.assertIn("2 stacks", txt)
        self.assertIn("inside your ship's cargo", txt)


class LoadTests(unittest.TestCase):
    def test_load_prefers_dense_value_and_respects_cargo(self):
        from eve_profit.stock import best_loads, format_loads
        con, g, far = setup()
        con.execute("DELETE FROM inventory")
        # Tritanium 0.01 m3 (cheap per m3) vs a 5 m3 item with a much better price per m3 is the Widget (16000/5)
        con.execute("INSERT INTO inventory VALUES(34,1,2000000)")        # 20,000 m3 of Tritanium
        con.execute("INSERT INTO inventory VALUES(36,1,100000)")         # Mexallon 1,000 m3, pricier per m3
        p = Profile(max_jumps=2, cargo_m3=5000, wallet_isk=1e9)
        loads = best_loads(con, g, p)
        self.assertTrue(loads)
        d = loads[0]
        self.assertLessEqual(d["used"], 5000 + 1e-6)
        dens = [v / u for _, u, v in d["items"]]                          # both items are 0.01 m3, so ISK/unit = ISK/m3 order
        self.assertEqual(dens, sorted(dens, reverse=True))                # densest value is loaded first
        self.assertIn("Best hold-loads", format_loads(loads))
        self.assertFalse([w for w in d["waypoints"] if g.is_red(w)])


class AlongTests(unittest.TestCase):
    def test_sells_where_best_along_route_and_travels_light(self):
        from eve_profit.along import format_along, plan_along
        con, g, far = setup()
        con.execute("DELETE FROM inventory")
        con.execute("DELETE FROM orders WHERE type_id IN (34,36)")
        path = g.route(1, far).path
        mid = path[1]
        now = 1.0
        # Tritanium: better price at the destination; Mexallon: best right here at the start
        con.execute("INSERT INTO orders VALUES(8001,34,60000099,?,10000001,1,9.0,10000000,1,'',?)", (far, now))
        con.execute("INSERT INTO orders VALUES(8002,34,60000098,1,10000001,1,5.0,10000000,1,'',?)", (now,))
        con.execute("INSERT INTO orders VALUES(8003,36,60000097,1,10000001,1,100.0,10000000,1,'',?)", (now,))
        con.execute("INSERT INTO orders VALUES(8004,36,60000096,?,10000001,1,60.0,10000000,1,'',?)", (far, now))
        con.execute("INSERT INTO inventory VALUES(34,1,100000)")
        con.execute("INSERT INTO inventory VALUES(36,1,5000)")
        res = plan_along(con, g, Profile(cargo_m3=5000), g.name[far])
        self.assertEqual([d["name"] for d in res["sell_here"]], ["Mexallon"])           # best at the start: sold there
        self.assertEqual([d["name"] for d in res["carry"]], ["Tritanium"])              # better at the destination: carried
        self.assertEqual(res["carry"][0]["at"], len(path) - 1)
        txt = format_along(res)
        self.assertIn("SELL IN Home", txt)
        self.assertIn("CARRY", txt)

    def test_carry_respects_hold(self):
        from eve_profit.along import plan_along
        con, g, far = setup()
        con.execute("DELETE FROM inventory")
        con.execute("DELETE FROM orders WHERE type_id=34")
        con.execute("INSERT INTO orders VALUES(8101,34,60000099,?,10000001,1,9.0,10000000,1,'',1)", (far,))
        con.execute("INSERT INTO inventory VALUES(34,1,1000000)")                        # 10,000 m3 of Tritanium
        res = plan_along(con, g, Profile(cargo_m3=2000), g.name[far])
        self.assertLessEqual(res["used_m3"], 2000 + 1e-6)
        self.assertEqual(res["carry"][0]["sold"], 200000)

    def test_empty_hangar_gives_instructions(self):
        from eve_profit.along import format_along, plan_along
        con, g, far = setup()
        con.execute("DELETE FROM inventory")
        txt = format_along(plan_along(con, g, Profile(cargo_m3=5000), g.name[far]))
        self.assertIn("No items found in your Home hangar", txt)
        self.assertIn("sync", txt)
