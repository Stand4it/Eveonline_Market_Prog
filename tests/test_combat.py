import os, tempfile, time, unittest
from eve_profit import db
from eve_profit.combat import find_combat, seed_defaults, calibrated_rate
from eve_profit.config import Profile
from eve_profit.graph import Graph
from eve_profit.mock import load_mock


def setup():
    con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
    load_mock(con)
    seed_defaults(con)
    return con


class T(unittest.TestCase):
    def test_no_dps_no_combat(self):
        con = setup()
        self.assertEqual(find_combat(con, Graph(con), Profile()), [])

    def test_dps_gate_and_salvage_variant(self):
        con = setup()
        p = Profile(max_jumps=3, combat_dps=200, can_salvage=True, ship_ehp=50000, ship_tank_dps=100)
        r = find_combat(con, Graph(con), p)
        names = {o.detail["activity"] for o in r}
        self.assertNotIn("Level 3 security mission", names)       # needs 300 dps
        self.assertIn("Level 2 security mission", names)
        base = next(o for o in r if o.kind == "combat" and "Level 2" in o.description)
        salv = next(o for o in r if o.kind == "combat+salv" and "Level 2" in o.description)
        self.assertGreater(salv.profit_isk, base.profit_isk)
        self.assertGreater(salv.hours, base.hours)

    def test_never_red_or_hot(self):
        con = setup()
        g = Graph(con)
        for o in find_combat(con, g, Profile(max_jumps=4, combat_dps=900, ship_ehp=90000, ship_tank_dps=300)):
            for part in o.route.split(" > "):
                self.assertFalse(g.is_red(g.id_of(part)))

    def test_unknown_ehp_recommends_nothing(self):
        con = setup()
        self.assertEqual(find_combat(con, Graph(con), Profile(combat_dps=900)), [])

    def test_win_assessment_and_filter(self):
        con = setup()
        g = Graph(con)
        weak = Profile(max_jumps=3, combat_dps=300, ship_ehp=2000, ship_tank_dps=0)
        self.assertEqual([o for o in find_combat(con, g, weak) if "Level 3" in o.description], [])
        strong = Profile(max_jumps=3, combat_dps=300, ship_ehp=60000, ship_tank_dps=150)
        o = next(o for o in find_combat(con, g, strong) if "Level 3" in o.description)
        self.assertGreaterEqual(o.detail["margin"], 3)
        self.assertLess(o.detail["p_lose"], 0.1)

    def test_risky_fight_allowed_only_if_profit_repays_ship(self):
        con = setup()
        g = Graph(con)
        # margin ~2: ehp 20000 vs dmg (250-0)*(60000/300)=50000*... tune: use L2
        p = Profile(max_jumps=3, combat_dps=150, ship_ehp=15000, ship_tank_dps=0,
                    ship_value_isk=2_000_000)   # cheap ship: 10M/h profit repays it
        self.assertTrue([o for o in find_combat(con, g, p) if "Level 2" in o.description])
        p.ship_value_isk = 500_000_000            # expensive ship: not worth the risk
        self.assertFalse([o for o in find_combat(con, g, p) if "Level 2" in o.description])

    def test_replacement_uses_cheaper_of_market_or_build(self):
        from eve_profit.combat import replacement_cost
        from eve_profit.orders import load_books
        con = setup()
        g = Graph(con)
        reach = g.reach(1, 3)
        sells, _ = load_books(con, reach)
        p = Profile(ship_type_id=90001, fit_value_isk=1000, insurance_payout_isk=500)
        con.execute("DELETE FROM my_blueprints")        # no blueprint -> must buy the hull
        market = min(a[0][0] for s_, a in sells[90001].items() if s_ in reach)
        self.assertAlmostEqual(replacement_cost(con, p, reach, sells), market + 500)
        con.execute("INSERT INTO my_blueprints VALUES(90002,100,0,-1)")   # ME100 -> ~free build
        self.assertLess(replacement_cost(con, p, reach, sells), market)

    def test_calibration_replaces_guess(self):
        con = setup()
        self.assertEqual(calibrated_rate(con, "x", 5.0), (5.0, False))
        for _ in range(3):
            con.execute("INSERT INTO activity_log(activity,isk,hours,ts) VALUES('x',30,2,?)",
                        (time.time(),))
        self.assertEqual(calibrated_rate(con, "x", 5.0), (15.0, True))


if __name__ == "__main__":
    unittest.main()
