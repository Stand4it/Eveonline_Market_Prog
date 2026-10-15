import json
import os
import sqlite3
import tempfile
import time
import unittest

from eve_profit import dailygoals


class TodayPool(unittest.TestCase):
    def test_today_file_filters_the_goal_set(self):
        f = os.path.join(tempfile.mkdtemp(), "d.json")
        json.dump({"seen": time.strftime("%Y-%m-%d"), "goals": ["Mine 2000 units of Ore", "Complete 3 Jumps"]}, open(f, "w"))
        os.environ["EVE_TODAY_FILE"] = f
        try:
            self.assertEqual(dailygoals.today_goals(), ["Mine 2000 units of Ore", "Complete 3 Jumps"])
            json.dump({"seen": "2000-01-01", "goals": ["x"]}, open(f, "w"))
            self.assertIsNone(dailygoals.today_goals())
        finally:
            del os.environ["EVE_TODAY_FILE"]


if __name__ == "__main__":
    unittest.main()
