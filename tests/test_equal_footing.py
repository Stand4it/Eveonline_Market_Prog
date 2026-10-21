import os
import tempfile
import unittest

from eve_profit import catalog, db


class EqualFooting(unittest.TestCase):
    def test_unmodeled_activities_get_a_comparable_rate_and_setup_lowers_it(self):
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        con.execute("INSERT INTO types(type_id,name,volume) VALUES(1,'Gallente Frigate',1),(2,'Small Hybrid Turret',1)")
        con.execute("INSERT INTO character_skills(skill_id,level) VALUES(1,5),(2,5)")
        plain = {d["act"]["id"]: d for d in catalog.equal_footing(con, 1e7, 3_000_000)}
        self.assertIn("agent_l2_security", plain)
        self.assertGreater(plain["agent_l2_security"]["eff"], 0)
        prepped = {d["act"]["id"]: d for d in catalog.equal_footing(con, 1e7, 3_000_000, extra_cost=lambda a: (60.0, 30000.0) if a["id"] == "agent_l2_security" else (0.0, 0.0))}
        self.assertLess(prepped["agent_l2_security"]["eff"], plain["agent_l2_security"]["eff"])
        self.assertEqual(prepped["agent_l2_security"]["prep_min"], 60.0)

    def test_an_untested_activity_is_worth_the_best_known_rate_until_set_up_costs_time(self):
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))      # owner rule 2026-10-21
        free = catalog.equal_footing(con, 1e7, 2_000_000)
        self.assertTrue(free)
        for d in free:
            if not d["prep_min"]:
                self.assertAlmostEqual(d["eff"], 2_000_000)
        setup = catalog.equal_footing(con, 1e7, 2_000_000, extra_cost=lambda a: (60.0, 0.0))
        for d in setup:
            self.assertLess(d["eff"], 2_000_000)


if __name__ == "__main__":
    unittest.main()
