import os, tempfile, unittest
from eve_profit import db
from eve_profit.combat import seed_defaults
from eve_profit.config import Profile
from eve_profit.graph import Graph
from eve_profit.mock import load_mock
from eve_profit.schedule import build_day, format_day, _hm


def world():
    con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
    load_mock(con)
    seed_defaults(con)
    return con, Graph(con)


def prof(**kw):
    d = dict(max_jumps=3, cargo_m3=5000, wallet_isk=5e7, min_profit_isk=1)
    d.update(kw)
    return Profile(**d)


class T(unittest.TestCase):
    def test_chain_respects_time_budget_and_never_reuses_a_task(self):
        con, g = world()
        res = build_day(con, g, prof(), hours=2.0)
        self.assertTrue(res["steps"])
        self.assertLessEqual(res["hours"], 2.0 + 1e-9)
        keys = [(s["kind"], s["what"]) for s in res["steps"]]
        self.assertEqual(len(keys), len(set(keys)))
        cums = [s["cum"] for s in res["steps"]]
        self.assertEqual(cums, sorted(cums))
        self.assertAlmostEqual(res["total"], cums[-1])
        self.assertAlmostEqual(res["per_hr"], res["total"] / res["hours"])

    def test_a_markets_depth_is_spent_once(self):
        con, g = world()
        res = build_day(con, g, prof(), hours=8.0)
        sells = []
        buys = []
        from eve_profit.planner import plan
        # re-derive each step's (type, from, to) by replanning from its start: here we just check descriptions for repeats
        for s in res["steps"]:
            if s["kind"] == "trade":
                what = s["what"]                      # "Buy N x ITEM @ A, sell @ B"
                item = what.split(" x ", 1)[1].split(" @ ")[0]
                a = what.split(" @ ")[1].split(",")[0]
                b = what.rsplit("sell @ ", 1)[1]
                buys.append((item, a)); sells.append((item, b))
        self.assertEqual(len(sells), len(set(sells)))
        self.assertEqual(len(buys), len(set(buys)))

    def test_more_hours_never_means_less_total(self):
        con, g = world()
        short = build_day(con, g, prof(), hours=1.0)["total"]
        long = build_day(con, g, prof(), hours=6.0)["total"]
        self.assertGreaterEqual(long, short)

    def test_next_step_starts_where_the_last_ended_and_wallet_grows(self):
        con, g = world()
        res = build_day(con, g, prof(), hours=6.0)
        for a, b in zip(res["steps"], res["steps"][1:]):
            self.assertEqual(b["from"], a["to"])
            self.assertAlmostEqual(b["wallet"], a["wallet"] + a["net"])
        self.assertEqual(build_day(con, g, prof(), hours=2.0, cash=1e8)["steps"][0]["wallet"], 1.5e8)

    def test_no_time_no_steps_and_format(self):
        con, g = world()
        res = build_day(con, g, prof(), hours=0.001)
        self.assertEqual(res["steps"], [])
        self.assertIn("No task fits", format_day(res))
        txt = format_day(build_day(con, g, prof(), hours=3.0))
        self.assertIn("ISK/jump", txt)
        self.assertIn("ISK/hr", txt)
        self.assertEqual(_hm(1.5), "1:30")


if __name__ == "__main__":
    unittest.main()
