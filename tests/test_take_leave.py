import unittest
from types import SimpleNamespace
from unittest import mock

from eve_profit import haul


class TakeLeave(unittest.TestCase):
    def test_when_the_hold_is_too_small_the_least_valuable_per_m3_stays(self):
        items = [("Ore", 1000, 400.0, 40_000.0), ("SKIN", 1, 0.01, 2_000_000.0), ("Junk", 10, 100.0, 1_000.0)]
        p = SimpleNamespace(cargo_m3=450.0, current_system="A")
        with mock.patch.object(haul, "_hangar_here", lambda con, g, p: items):
            L = "\n".join(haul.take_leave(None, None, p))
        self.assertIn("TAKE  1 x SKIN", L)
        self.assertIn("TAKE  1,000 x Ore", L)
        self.assertIn("LEAVE 10 x Junk", L)

    def test_nothing_listed_when_all_fits(self):
        p = SimpleNamespace(cargo_m3=450.0, current_system="A")
        with mock.patch.object(haul, "_hangar_here", lambda con, g, p: [("SKIN", 1, 0.01, 1.0)]):
            self.assertEqual(haul.take_leave(None, None, p), [])


if __name__ == "__main__":
    unittest.main()
