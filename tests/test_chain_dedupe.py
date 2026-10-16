import unittest

from eve_profit.nextstep import _chain


class TestChainDedupe(unittest.TestCase):
    def test_same_step_twice_is_one_step(self):
        a = "STEP: FLY to Yulai\n   DO ONLY THIS: fly\nThen run: now"
        b = "STEP: FLY to Yulai\n   DO ONLY THIS: fly"
        self.assertEqual(_chain([a, b]), a)

    def test_two_different_steps_stay_a_chain(self):
        self.assertIn("TODAY'S CHAIN - 2", _chain(["STEP: A\n x", "STEP: B\n y"]))


if __name__ == "__main__":
    unittest.main()
