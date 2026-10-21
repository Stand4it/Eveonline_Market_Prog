import sqlite3
import unittest

from eve_profit import catalog


class T(unittest.TestCase):
    def test_lp_gate(self):
        a = {"lp_min": 1000}
        self.assertTrue(catalog.missing_for(a, {}, 0.0, 0))
        self.assertFalse(catalog.missing_for(a, {}, 0.0, 5000))
        con = sqlite3.connect(":memory:")
        self.assertEqual(catalog.lp_total(con), 0)
        con.execute("CREATE TABLE lp_balance(corporation_id INTEGER PRIMARY KEY, points INTEGER NOT NULL)")
        con.execute("INSERT INTO lp_balance VALUES(1000419,17500)")             # EverMarks is not LP
        self.assertEqual(catalog.lp_total(con), 0)
        con.execute("INSERT INTO lp_balance VALUES(1000001,2500)")
        self.assertEqual(catalog.lp_total(con), 2500)


if __name__ == "__main__":
    unittest.main()


class HullGate(unittest.TestCase):
    def test_hull_gate(self):
        a = {"needs_hull": ["Imicus", "Heron"]}
        self.assertTrue(catalog.missing_for(a, {}, 0.0, 0, "Capsule - Stand4it Dahl"))
        self.assertFalse(catalog.missing_for(a, {}, 0.0, 0, "Imicus - Stand4it Dahl"))
        self.assertFalse(catalog.missing_for(a, {}, 0.0, 0, None))          # no ship info: no gate


class OwnedShip(unittest.TestCase):
    def test_owned_ship_unlocks(self):
        a = {"needs_hull": ["Imicus"]}
        self.assertTrue(catalog.missing_for(a, {}, 0.0, 0, "Capsule - X", ()))
        self.assertFalse(catalog.missing_for(a, {}, 0.0, 0, "Capsule - X", ("Imicus", "Venture")))      # you own one: planned, not locked


class BlueprintGate(unittest.TestCase):
    def test_bp_gate(self):
        a = {"needs_bp": True}
        self.assertTrue(catalog.missing_for(a, {}, 0.0, 0, None, (), 0))
        self.assertFalse(catalog.missing_for(a, {}, 0.0, 0, None, (), 2))
        self.assertFalse(catalog.missing_for(a, {}, 0.0, 0, None, (), None))      # unknown: no gate


class GunToolGate(unittest.TestCase):
    def test_gun_tool_is_a_known_tool(self):
        from eve_profit import tools
        a = {"needs_tool": "gun"}
        t = {"fitted": {k: 0 for k in tools.TOOLS}, "held": {k: 0 for k in tools.TOOLS}}
        self.assertTrue(catalog.missing_for(a, {}, 0.0, 0, "Capsule - X", (), None, t))     # was a KeyError: 'gun'
        t["fitted"]["gun"] = 2
        self.assertFalse(catalog.missing_for(a, {}, 0.0, 0, "Catalyst - X", (), None, t))

