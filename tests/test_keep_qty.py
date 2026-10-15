import unittest

from eve_profit.along import keep_split


class KeepQty(unittest.TestCase):
    def test_only_the_keep_qty_is_held_back(self):
        rules = {"anode cannon": {"qty": 1, "item": "Anode Cannon"}, "probe": {"qty": None, "item": "Probe"}}
        self.assertEqual(keep_split(rules, "Anode Cannon", 6), (1, 5))
        self.assertEqual(keep_split(rules, "Probe", 8), (8, 0))
        self.assertEqual(keep_split(rules, "Other", 3), (0, 3))


if __name__ == "__main__":
    unittest.main()
