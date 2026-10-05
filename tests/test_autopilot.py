import os, tempfile, unittest
from eve_profit import db
from eve_profit.autopilot import dedupe, route_alerts, send_route
from eve_profit.combat import seed_defaults
from eve_profit.config import Profile
from eve_profit.graph import Graph
from eve_profit.mock import load_mock
from eve_profit.planner import plan


class Rec:
    def __init__(self): self.calls = []
    def post(self, path, **kw): self.calls.append(kw)


def setup():
    con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
    load_mock(con)
    seed_defaults(con)
    return con, Graph(con)


class T(unittest.TestCase):
    def test_dedupe(self):
        self.assertEqual(dedupe([1, 1, 2, 2, 3, 2]), [1, 2, 3, 2])

    def test_dry_run_sends_nothing_and_send_clears_first(self):
        con, g = setup()
        r = Rec()
        send_route(r, g, [1, 2], send=False)
        self.assertEqual(r.calls, [])
        send_route(r, g, [1, 2], send=True, pause=0)
        self.assertEqual([c["clear_other_waypoints"] for c in r.calls], ["true", "false"])

    def test_refuses_red(self):
        con, g = setup()
        red = next(s for s in g.adj if g.is_red(s))
        with self.assertRaises(ValueError):
            send_route(Rec(), g, [1, red], send=True)

    def test_every_opportunity_has_safe_waypoints(self):
        con, g = setup()
        p = Profile(max_jumps=3, combat_dps=400, can_salvage=True, ship_ehp=100000, ship_tank_dps=300, mining_yield_m3_s=0.5,
                    minable_ores=["Veldspar"], assume_all_blueprints=True, min_profit_isk=1,
                    wallet_isk=1e9, cargo_m3=50000)
        opps = plan(con, p, 200, False)
        self.assertTrue(opps)
        for o in opps:
            if o.jumps:
                self.assertTrue(o.waypoints, o.kind)
            self.assertFalse([w for w in o.waypoints if g.is_red(w)], o.kind)

    def test_alerts_flag_hot(self):
        con, g = setup()
        self.assertIn(("Sys05", "HOT"), route_alerts(g, [2, 5]))


if __name__ == "__main__":
    unittest.main()
