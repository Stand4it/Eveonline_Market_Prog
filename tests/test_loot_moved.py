import unittest

from eve_profit.loot import gains


class LootMoved(unittest.TestCase):
    def test_moving_a_stack_is_not_loot(self):
        self.assertEqual(gains({"5:1": 6}, {"5:2": 6}), [])

    def test_real_gain_counts(self):
        self.assertEqual(gains({"5:1": 6}, {"5:2": 6, "9:2": 3}), [(9, 2, 3)])
        self.assertEqual(gains({"5:1": 2}, {"5:1": 2, "5:2": 4}), [(5, 2, 4)])


if __name__ == "__main__":
    unittest.main()
