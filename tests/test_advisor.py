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


class DiagTests(unittest.TestCase):
    def test_diag_runs_and_reports_missing_pieces(self):
        from eve_profit.diag import diagnose
        con = setup()
        out = diagnose(con, Profile(ship_name="X", ship_type_id=999999))
        self.assertIn("MISSING", out)
        self.assertIn("skill types with a rank", out)


class FillTests(unittest.TestCase):
    class E:
        calls = 0
        def type_info(self, tid):
            self.calls += 1
            return {"dogma_attributes": [{"attribute_id": 275, "value": 3}, {"attribute_id": 180, "value": 165},
                                         {"attribute_id": 181, "value": 164}, {"attribute_id": 38, "value": 5500}]}

    def test_fill_skill_info_only_for_missing(self):
        from eve_profit.advisor import fill_skill_info
        con = setup()
        e = self.E()
        con.execute("UPDATE types SET skill_rank=NULL WHERE type_id=16622")
        n = fill_skill_info(con, e, [16622, 3380])           # 3380 already has a rank
        self.assertEqual((n, e.calls), (1, 1))
        self.assertEqual(tuple(con.execute("SELECT skill_rank,skill_primary,skill_secondary FROM types WHERE type_id=16622").fetchone()),
                         (3, 165, 164))

    def test_hauler_named_skill_gives_cargo_bonus_and_capacity_fill(self):
        from eve_profit.advisor import hull_racial_skill
        from eve_profit.character import _fill_capacity, _hull_cargo_bonus
        con = setup()
        con.execute("INSERT INTO types(type_id,name,volume) VALUES(652,'Mammoth',255000)")
        con.execute("INSERT INTO types(type_id,name,volume) VALUES(3341,'Minmatar Hauler',0.01)")
        con.execute("INSERT INTO type_skills VALUES(652,3341,1)")
        self.assertEqual(hull_racial_skill(con, Profile(ship_type_id=652)), "Minmatar Hauler")
        self.assertAlmostEqual(_hull_cargo_bonus(con, 652, [{"skill_id": 3341, "trained_skill_level": 4}]), 1.20)
        _fill_capacity(con, self.E(), 652)
        self.assertEqual(con.execute("SELECT capacity FROM types WHERE type_id=652").fetchone()[0], 5500)


class StockSkillTests(unittest.TestCase):
    def test_broker_and_slot_skills_have_value_on_listable_stock(self):
        from eve_profit.advisor import stock_skill_gains
        con = setup()
        con.execute("DELETE FROM inventory"); con.execute("DELETE FROM orders WHERE type_id IN (34,35,36)")
        for oid, tid, buy, price in [(9001, 34, 1, 1.0), (9002, 34, 0, 100.0), (9003, 35, 1, 1.0), (9004, 35, 0, 90.0),
                                     (9005, 36, 1, 1.0), (9006, 36, 0, 80.0)]:
            con.execute("INSERT INTO orders VALUES(?,?,60000001,1,10000001,?,?,10000000,1,'',1)", (oid, tid, buy, price))
        for tid in (34, 35, 36):
            con.execute("INSERT INTO inventory VALUES(?,1,1000)", (tid,))
        con.execute("DELETE FROM character_skills")
        con.executemany("INSERT INTO character_skills(skill_id,level) VALUES(?,?)", [(3443, 0), (3446, 0)])   # 5 slots, 3% fee
        con.execute("UPDATE types SET skill_rank=1 WHERE type_id IN (3380)")
        p = Profile(current_location_id=60000001, broker_fee=0.03, secs_per_jump=45)
        gains = {d["skill"]: d["gain"] for d in stock_skill_gains(con, p)}
        self.assertGreater(gains["Broker Relations"], 0)                      # cheaper listing fee => more ISK on every listed stack
        # 5 slots already list all 3 stacks, so extra slots add nothing here:
        self.assertEqual(gains["Trade"], 0)
        # with only 1 slot the other stacks are sold instantly, so slots become valuable
        con.execute("UPDATE character_skills SET level=0 WHERE skill_id=3443")
        from unittest import mock
        with mock.patch("eve_profit.skills.order_slots", return_value=1):
            gains = {d["skill"]: d["gain"] for d in stock_skill_gains(con, p)}
        self.assertGreater(gains["Trade"], 0)
        self.assertGreaterEqual(gains["Retail"], gains["Trade"])                # +8 slots is never worse than +4
