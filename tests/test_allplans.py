import sqlite3
import unittest
from types import SimpleNamespace
from unittest import mock

from eve_profit import allplans


class T(unittest.TestCase):
    def _con(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.execute("CREATE TABLE activity_log(activity TEXT, isk REAL, hours REAL)")
        con.execute("CREATE TABLE skills(skill_id INTEGER, name TEXT, level INTEGER)")
        return con

    def test_every_activity_on_one_list_by_isk_per_minute(self):
        p = SimpleNamespace(wallet_isk=1_000_000.0, current_system="A")
        with mock.patch("eve_profit.shopping.blocked_goals", return_value=[{"goal": "Scan 5 Signatures", "per_min": 6000.0, "lines": ["hull: x"], "why": ""}]):
            rs = allplans.rows(self._con(), None, p, 300_000.0)
        self.assertGreater(len(rs), 5)
        self.assertEqual([r["per_min"] for r in rs], sorted((r["per_min"] for r in rs), reverse=True))
        d = next(r for r in rs if r["kind"] == "daily")
        self.assertFalse(d["ready"])
        self.assertTrue(any(r["info"] > 0 for r in rs))               # untimed ones carry the value of what timing them teaches

    def test_lines_lists_missing_prerequisites(self):
        p = SimpleNamespace(wallet_isk=0.0, current_system="A")
        with mock.patch("eve_profit.shopping.blocked_goals", return_value=[]):
            txt = allplans.lines(self._con(), None, p, [(300_000.0, "x", "", "")])
        self.assertIn("EVERYTHING BY ISK PER MINUTE", txt)
        self.assertIn("needs:", txt)


if __name__ == "__main__":
    unittest.main()
