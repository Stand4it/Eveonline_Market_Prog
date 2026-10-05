import math, os, tempfile, unittest
from eve_profit import db
from eve_profit.advisor import advise, format_advice, fmt_minutes, sp_for_level, train_minutes, virtual_levels
from eve_profit.combat import seed_defaults
from eve_profit.config import Profile
from eve_profit.mock import load_mock
from eve_profit.planner import plan


def setup():
    con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
    load_mock(con)
    seed_defaults(con)
    con.executemany("INSERT INTO types(type_id,name,volume,skill_rank,skill_primary,skill_secondary) VALUES(?,?,0.01,?,?,?)",
                    [(16622, "Accounting", 3, 164, 165), (24625, "Advanced Mass Production", 8, 165, 166)])
    con.execute("UPDATE types SET skill_rank=1, skill_primary=165, skill_secondary=166 WHERE type_id IN (3380,3387,3388)")
    con.executemany("INSERT INTO char_attrs VALUES(?,?)", [("charisma", 20), ("intelligence", 27), ("memory", 21),
                                                           ("perception", 20), ("willpower", 20)])
    con.execute("INSERT INTO character_skills(skill_id,level,sp) VALUES(16622,4,100000)")
    return con


class T(unittest.TestCase):
    def test_sp_formula(self):
        self.assertEqual([round(sp_for_level(1, n)) for n in range(1, 6)], [250, 1414, 8000, 45255, 256000])
        self.assertEqual(sp_for_level(3, 5), 768000)

    def test_train_minutes_uses_attributes_and_partial_sp(self):
        # level 5 of a rank-3 skill: 768,000 total; already 100,000 SP in level (4 done = 135,765) -> use level-4 SP as floor
        m = train_minutes(3, 5, 100000, 27, 21)
        self.assertAlmostEqual(m, (768000 - 135764.5) / (27 + 10.5), delta=1)
        self.assertEqual(fmt_minutes(90), "1h 30m")
        self.assertEqual(fmt_minutes(60 * 49), "2d 1h")

    def test_accounting_v_is_recommended_with_a_gain(self):
        con = setup()
        p = Profile(max_jumps=3, cargo_m3=5000, wallet_isk=1e9, min_profit_isk=1, accounting_level=4)
        res = advise(con, p, plan, hours=24 * 400)
        acc = [s for s in res["steps"] if s["skill"] == "Accounting"]
        self.assertEqual([s["level"] for s in acc], [5])
        self.assertGreater(acc[0]["gain"], 0)                       # lower tax -> more ISK/hr
        self.assertGreater(acc[0]["minutes"], 0)
        self.assertIn("Accounting", format_advice(res))

    def test_prereqs_block_and_queue_counts_as_trained(self):
        con = setup()
        con.execute("INSERT INTO type_skills VALUES(24625,3380,5)")   # Adv Mass Production needs Industry 5 (we have none)
        p = Profile(max_jumps=3, cargo_m3=5000, wallet_isk=1e9, min_profit_isk=1)
        res = advise(con, p, plan, hours=10000)
        self.assertFalse([s for s in res["steps"] if s["skill"] == "Advanced Mass Production"])
        self.assertTrue([n for n in res["notes"] if "prerequisites" in n])
        con.execute("INSERT INTO skill_queue VALUES(1,16622,5,NULL)")
        self.assertEqual(virtual_levels(con)[16622], 5)
        res = advise(con, p, plan, hours=10000)
        self.assertFalse([s for s in res["steps"] if s["skill"] == "Accounting"])   # already queued to V

    def test_greedy_orders_by_gain_per_training_hour_and_respects_budget(self):
        con = setup()
        con.execute("DELETE FROM character_skills")                      # untrained Accounting
        p = Profile(max_jumps=3, cargo_m3=5000, wallet_isk=1e9, min_profit_isk=1, accounting_level=0)
        res = advise(con, p, plan, hours=1)
        self.assertTrue(res["steps"])                                  # always takes at least the best step
        self.assertEqual([s["level"] for s in res["steps"] if s["skill"] == "Accounting"][:1], [1])
        full = advise(con, p, plan, hours=10000)
        accl = [s["level"] for s in full["steps"] if s["skill"] == "Accounting"]
        self.assertEqual(accl, sorted(accl))                           # levels in order

    def test_no_attributes_gives_a_note(self):
        con = setup()
        con.execute("DELETE FROM char_attrs")
        res = advise(con, Profile(max_jumps=2), plan, hours=5)
        self.assertTrue([n for n in res["notes"] if "attributes" in n])


if __name__ == "__main__":
    unittest.main()
