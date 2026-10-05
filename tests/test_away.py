import os, tempfile, unittest
from eve_profit import db
from eve_profit.autopilot import send_route
from eve_profit.combat import seed_defaults
from eve_profit.config import Profile
from eve_profit.graph import Graph
from eve_profit.mock import load_mock
from eve_profit.planner import away_profile, plan


def setup():
    con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
    load_mock(con)
    seed_defaults(con)
    return con, Graph(con)


class Rec:
    def __init__(self): self.calls = []
    def post(self, path, **kw): self.calls.append(kw)


class T(unittest.TestCase):
    def test_away_profile(self):
        a = away_profile(Profile(max_jumps=2))
        self.assertEqual((a.autopilot, a.max_jumps, a.pickup, a.avoid_yellow, a.consider_ship_swaps),
                         (True, 15, 3, True, False))
        self.assertGreater(a.jump_seconds, Profile().jump_seconds)          # autopilot is slower

    def test_away_plan_only_hauls_and_never_touches_yellow_or_hot(self):
        con, g = setup()
        p = Profile(max_jumps=2, away_mode=True, away_max_jumps=8, cargo_m3=5000, wallet_isk=1e9,
                    min_profit_isk=1, combat_dps=900, ship_ehp=300000, ship_tank_dps=500,
                    mining_yield_m3_s=0.5, minable_ores=["Veldspar"], assume_all_blueprints=True)
        opps = plan(con, p, 100000, False)
        self.assertTrue(opps)
        self.assertTrue({o.kind for o in opps} <= {"trade", "liquidate", "courier", "contract", "lp-redeem"})
        for o in opps:
            for w in o.waypoints:
                self.assertFalse(g.is_red(w) or g.is_yellow(w) or g.is_hot(w), (o.description, g.name[w]))

    def test_away_risk_is_higher_than_attended(self):
        con, g = setup()
        base = dict(max_jumps=3, cargo_m3=5000, wallet_isk=1e9, min_profit_isk=1)
        att = {o.description: o for o in plan(con, Profile(**base), 100000, False) if o.kind == "trade"}
        away = {o.description: o for o in plan(con, Profile(away_mode=True, away_max_jumps=3, pickup_jumps=3, **base),
                                               100000, False) if o.kind == "trade"}
        common = [d for d in away if d in att and att[d].jumps > 0]
        self.assertTrue(common)
        d = common[0]
        self.assertGreater(away[d].risk_cost_isk, att[d].risk_cost_isk)
        self.assertGreater(away[d].hours, att[d].hours)

    def test_trades_carry_dock_stops_and_send_route_uses_them(self):
        con, g = setup()
        p = Profile(max_jumps=3, cargo_m3=5000, wallet_isk=1e9, min_profit_isk=1)
        o = next(o for o in plan(con, p, 100000, False) if o.kind == "trade" and o.detail["stops"])
        stops = o.detail["stops"]
        self.assertEqual(len(stops), 2)
        self.assertTrue(all(loc >= 60000000 for _, loc in stops))
        r = Rec()
        send_route(r, g, o.waypoints, send=True, pause=0, stops=stops)
        dests = [c["destination_id"] for c in r.calls]
        self.assertEqual(dests[-1], stops[-1][1])                  # ends AT the selling station
        self.assertIn(stops[0][1], dests)                          # and passes the buying station
        self.assertEqual(r.calls[0]["clear_other_waypoints"], "true")


if __name__ == "__main__":
    unittest.main()
