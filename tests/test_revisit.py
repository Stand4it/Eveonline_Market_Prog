import json
import sqlite3
import time
import unittest

from eve_profit import livepos


class Revisit(unittest.TestCase):
    def test_systems_of_the_last_moves_are_remembered_except_here(self):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
        now = time.time()
        log = [[now - 600, "Uedama", "Sivala", 1], [now - 500, "Sivala", "Kamio", 1], [now - 400, "Kamio", "Halaima", 1], [now - 300, "Halaima", "Huttaken", 1]]
        con.execute("INSERT INTO meta VALUES('jump_log', ?)", (json.dumps(log),))
        seen = livepos.recent_systems(con, "Huttaken", now=now)
        self.assertIn("halaima", seen)                                   # going back to Halaima from Huttaken is a loop
        self.assertIn("uedama", seen)
        self.assertNotIn("huttaken", seen)
        old = [[now - 5 * 3600, "Jita", "Perimeter", 1]]
        con.execute("INSERT OR REPLACE INTO meta VALUES('jump_log', ?)", (json.dumps(old),))
        self.assertEqual(livepos.recent_systems(con, "Perimeter", now=now), set())   # older than 3 h: free again


if __name__ == "__main__":
    unittest.main()
