import sqlite3
import unittest
from datetime import date

from eve_profit import airclaim


class TestAirClaim(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")

    def test_shown_daily_until_the_reset_then_never(self):
        rate, text = airclaim.candidate(self.con, date(2026, 10, 21))
        self.assertIn("CLAIM YOUR AIR CAREER REWARDS", text)
        self.assertLess(rate, 1e12)
        airclaim.mark(self.con, date(2026, 10, 21))
        self.assertIsNone(airclaim.candidate(self.con, date(2026, 10, 21)))      # claimed today
        self.assertIsNotNone(airclaim.candidate(self.con, date(2026, 10, 22)))   # back the next day
        self.assertIsNone(airclaim.candidate(self.con, date(2026, 11, 10)))      # reset day: gone

    def test_last_two_days_go_first(self):
        self.assertEqual(airclaim.candidate(self.con, date(2026, 11, 8))[0], 1e12)


if __name__ == "__main__":
    unittest.main()

