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


class TestScanNeedsLauncher(unittest.TestCase):
    def test_scan_goal_not_offered_without_a_fitted_launcher(self):
        from unittest import mock
        from eve_profit import dailygoals as d
        with mock.patch.object(d, "_has_skill", return_value=True), mock.patch.object(d, "_fitted_names", return_value=[]):
            o = d.scan_option(None)
        self.assertFalse(o["ok"])
        with mock.patch.object(d, "_has_skill", return_value=True), mock.patch.object(d, "_fitted_names", return_value=["core probe launcher i"]), mock.patch.object(d, "_min_ask", return_value=1000.0):
            self.assertTrue(d.scan_option(None)["ok"])


if __name__ == "__main__":
    unittest.main()
