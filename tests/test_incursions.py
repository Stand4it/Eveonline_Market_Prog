import json
import sqlite3
import unittest
from types import SimpleNamespace

from eve_profit import incursions


class FakeESI:
    def get(self, path):
        assert path == "/incursions/"
        return [{"constellation_id": 7, "staging_solar_system_id": 2, "state": "established", "influence": 0.4, "has_boss": True}], 1


class G:
    name = {1: "A", 2: "B"}
    sec = {1: 0.9, 2: 0.5}

    def id_of(self, n):
        return 1

    def reach(self, cur, n, avoid):
        return {1: SimpleNamespace(jumps=0), 2: SimpleNamespace(jumps=3)}


class T(unittest.TestCase):
    def test_fetch_and_near(self):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
        summary, frac, _ = incursions.fetch(con, FakeESI())
        self.assertIn("1 active", summary)
        self.assertEqual(frac, 1.0)
        rows = incursions.near(con, G(), SimpleNamespace(current_system="A"))
        self.assertEqual(rows[0][:3], (3, "B", "established"))
        self.assertIn("3 jumps: staging B", incursions.lines(con, G(), SimpleNamespace(current_system="A")))


if __name__ == "__main__":
    unittest.main()
