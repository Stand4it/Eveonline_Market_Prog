import os, tempfile, unittest
from eve_profit import db
from eve_profit.combat import seed_defaults
from eve_profit.config import Profile
from eve_profit.graph import Graph
from eve_profit.mock import load_mock
from unittest import mock
from eve_profit.sellplan import format_sellplan, sell_plan as _sell_plan


def sell_plan(*a, **k):
    """The mock market has a ~100M ISK/hr trade; pin the value of time so tests are about the logic, not the mock."""
    with mock.patch("eve_profit.sellplan.plan", return_value=[]):
        return _sell_plan(*a, **k)


def world():
    con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
    load_mock(con)
    seed_defaults(con)
    g = Graph(con)
    con.execute("DELETE FROM inventory"); con.execute("DELETE FROM orders WHERE type_id IN (34,35,36)")
    r = g.reach(1, 3)
    path = g.route(1, [s for s, x in r.items() if x.jumps == 2][0]).path
    return con, g, path


def bid(con, oid, tid, system, price, qty=10**9):
    con.execute("INSERT INTO orders VALUES(?,?,?,?,10000001,1,?,?,1,'',1)", (oid, tid, 60000000 + system, system, price, qty))


def prof(**kw):
    d = dict(max_jumps=3, cargo_m3=100000, wallet_isk=1e9, min_profit_isk=1, current_location_id=60000001, secs_per_jump=45)
    d.update(kw)
    return Profile(**d)


class T(unittest.TestCase):
    def test_carry_on_the_trip_when_it_pays_and_costs_almost_no_time(self):
        con, g, path = world()
        bid(con, 1, 34, 1, 5.0); bid(con, 2, 34, path[-1], 8.0)                 # 60% better at the end of your trip
        con.execute("INSERT INTO inventory VALUES(34,1,1000000)")
        res = sell_plan(con, g, prof(), dest=g.name[path[-1]])
        x = res["rows"][0]
        self.assertTrue(x["best_label"].startswith("CARRY along the trip"), x["best_label"])
        self.assertGreater(x["extra"], 0)
        self.assertLessEqual(x["mins"], 2.0)
        self.assertIn("CARRY along the trip", format_sellplan(res))

    def test_detour_is_rejected_when_the_time_costs_more_than_it_earns(self):
        con, g, path = world()
        off = next(s for s, r in g.reach(1, 3).items() if s not in path and r.jumps == 3 and not g.is_red(s))
        bid(con, 3, 34, 1, 5.0); bid(con, 4, 34, off, 5.4)                       # only 8% better, 3 jumps off the trip
        con.execute("INSERT INTO inventory VALUES(34,1,1000000)")
        res = sell_plan(con, g, prof(), dest=g.name[path[-1]], rate=10_000_000)      # time is worth 10M ISK/hr
        self.assertTrue(res["rows"][0]["best_label"].startswith("SELL NOW"))
        res = sell_plan(con, g, prof(), dest=g.name[path[-1]], rate=500_000)        # cheap time: the detour is fine
        self.assertTrue(res["rows"][0]["best_label"].startswith("DETOUR"))

    def test_big_stack_justifies_a_detour_small_one_does_not(self):
        con, g, path = world()
        off = next(s for s, r in g.reach(1, 3).items() if s not in path and r.jumps == 2 and not g.is_red(s))
        bid(con, 5, 35, 1, 10.0); bid(con, 6, 35, off, 14.0)
        con.execute("INSERT INTO inventory VALUES(35,1,50000000)")               # 40% better on a huge stack
        res = sell_plan(con, g, prof(cargo_m3=1e9), dest=g.name[path[-1]])
        self.assertTrue(res["rows"][0]["best_label"].startswith("DETOUR"), res["rows"][0]["best_label"])
        con.execute("UPDATE inventory SET quantity=20000 WHERE type_id=35")      # same prices, tiny stack
        res = sell_plan(con, g, prof(cargo_m3=1e9), dest=g.name[path[-1]], min_value=1, rate=1_000_000)
        self.assertTrue(res["rows"][0]["best_label"].startswith("SELL NOW"))

    def test_worldwide_haul_considered_only_with_data_and_charges_round_trip(self):
        con, g, path = world()
        bid(con, 7, 36, 1, 100.0)
        con.execute("INSERT INTO inventory VALUES(36,1,2000000)")                # 200M of Mexallon here at 100
        far = max(g.reach(1, 40).items(), key=lambda kv: kv[1].jumps)
        rows = [{"net": 200_000_000 * 1.5, "system": g.name[far[0]], "jumps": far[1].jumps, "gank": 0, "units": 2000000}]
        res = sell_plan(con, g, prof(), world={36: rows})
        self.assertTrue(res["rows"][0]["best_label"].startswith("HAUL to"), res["rows"][0]["best_label"])
        self.assertGreater(res["rows"][0]["mins"], 2 * far[1].jumps * 0.5)       # a round trip, not one way
        res = sell_plan(con, g, prof())                                          # no worldwide data => cannot haul
        self.assertFalse(res["rows"][0]["best_label"].startswith("HAUL"))

    def test_full_hold_forces_sell_now_for_the_overflow(self):
        con, g, path = world()
        bid(con, 8, 34, 1, 5.0); bid(con, 9, 34, path[-1], 9.0)
        con.execute("INSERT INTO inventory VALUES(34,1,1000000)")                # 10,000 m3 of Tritanium
        res = sell_plan(con, g, prof(cargo_m3=1000), dest=g.name[path[-1]])
        self.assertIn("hold full", res["rows"][0]["best_label"])


if __name__ == "__main__":
    unittest.main()
