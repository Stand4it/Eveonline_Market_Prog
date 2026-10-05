import os, tempfile, unittest
from eve_profit import db
from eve_profit.config import Profile
from eve_profit.graph import Graph
from eve_profit.manufacturing import find_manufacturing
from eve_profit.mock import load_mock
from eve_profit.planner import plan
from eve_profit.skills import blocked_blueprints, free_slots, missing


def setup():
    con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
    load_mock(con)
    con.execute("UPDATE orders SET price=price*1.5 WHERE is_buy=1 AND type_id=90001")  # make build profitable
    return con, Graph(con)


def prof(**kw):
    return Profile(max_jumps=3, cargo_m3=100000, wallet_isk=1e9, min_profit_isk=1, min_margin=0, **kw)


class T(unittest.TestCase):
    def test_missing(self):
        self.assertEqual(missing([(1, 3), (2, 1)], {1: 2, 2: 5}), [(1, 3, 2)])

    def test_unsynced_skills_skip_check(self):
        con, g = setup()
        self.assertTrue(find_manufacturing(con, g, prof()))

    def test_lacking_skill_blocks_build_and_is_explained(self):
        con, g = setup()
        con.execute("INSERT INTO character_skills VALUES(3380,2)")        # needs 3
        self.assertEqual(find_manufacturing(con, g, prof()), [])
        self.assertIn("Industry 3 (have 2)", blocked_blueprints(con, prof())[0][1])
        con.execute("UPDATE character_skills SET level=3")
        self.assertTrue(find_manufacturing(con, g, prof()))

    def test_no_free_slot_no_builds(self):
        con, g = setup()
        p = prof(mfg_slots_total=2, mfg_slots_used=2)
        self.assertEqual(free_slots(p), 0)
        self.assertEqual(find_manufacturing(con, g, p), [])

    def test_planner_caps_builds_to_free_slots(self):
        con, g = setup()
        con.execute("INSERT INTO my_blueprints VALUES(90002,0,0,-1)")     # second copy -> 2 candidates
        p = prof(mfg_slots_total=1)
        self.assertEqual(sum(o.kind == "build" for o in plan(con, p, 100000, False)), 1)
        p = prof(mfg_slots_total=2)
        self.assertEqual(sum(o.kind == "build" for o in plan(con, p, 100000, False)), 2)

    def test_bpc_runs_limit(self):
        con, g = setup()
        con.execute("UPDATE my_blueprints SET runs=2")
        o = find_manufacturing(con, g, prof())[0]
        self.assertLessEqual(o.detail["runs"], 2)

    def test_ore_skill_gate(self):
        from eve_profit.mining import find_mining
        con, g = setup()
        con.execute("INSERT INTO type_skills VALUES(1230,3380,5)")        # Veldspar "needs" Industry 5
        con.execute("INSERT INTO character_skills VALUES(3380,3)")
        p = prof(mining_yield_m3_s=0.5, minable_ores=["Veldspar"])
        self.assertEqual(find_mining(con, g, p), [])
        con.execute("UPDATE character_skills SET level=5")
        self.assertTrue(find_mining(con, g, p))


if __name__ == "__main__":
    unittest.main()
