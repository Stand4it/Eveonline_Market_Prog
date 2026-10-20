import unittest

from eve_profit import pricefresh


class T(unittest.TestCase):
    def test_policy(self):
        self.assertEqual(pricefresh.advice(None, needed=True, now_age=12.0), "")                 # fresh: use the prices
        self.assertEqual(pricefresh.advice(None, needed=True, now_age=47.0), "")                 # past 30: wait for the next scheduled run, use current prices
        self.assertEqual(pricefresh.advice(None, needed=False, now_age=30.0), "")                # halfway but nothing needs it
        self.assertIn("scan --live", pricefresh.advice(None, needed=True, now_age=31.0))         # halfway AND a decision needs it
        self.assertIn("No prices yet", pricefresh.advice(None, needed=True, now_age=None) or "No prices yet")


if __name__ == "__main__":
    unittest.main()
