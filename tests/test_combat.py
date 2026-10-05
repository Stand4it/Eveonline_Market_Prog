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
        p = Profile(max_jumps=3, combat_dps=200, can_salvage=True)
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
        for o in find_combat(con, g, Profile(max_jumps=4, combat_dps=900)):
            for part in o.route.split(" > "):
                self.assertFalse(g.is_red(g.id_of(part)))

    def test_calibration_replaces_guess(self):
        con = setup()
        self.assertEqual(calibrated_rate(con, "x", 5.0), (5.0, False))
        for _ in range(3):
            con.execute("INSERT INTO activity_log(activity,isk,hours,ts) VALUES('x',30,2,?)",
                        (time.time(),))
        self.assertEqual(calibrated_rate(con, "x", 5.0), (15.0, True))


if __name__ == "__main__":
    unittest.main()
