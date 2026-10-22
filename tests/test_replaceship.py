import unittest
from types import SimpleNamespace

from eve_profit import replaceship


class ReplaceShip(unittest.TestCase):
    def test_only_in_a_capsule(self):
        self.assertTrue(replaceship.in_capsule(SimpleNamespace(ship_name="Capsule")))
        self.assertTrue(replaceship.in_capsule(SimpleNamespace(ship_name="")))
        self.assertFalse(replaceship.in_capsule(SimpleNamespace(ship_name="Catalyst - Stand4it Dahl")))
        self.assertIsNone(replaceship.candidate(None, None, SimpleNamespace(ship_name="Catalyst"), 1e6))


if __name__ == "__main__":
    unittest.main()
