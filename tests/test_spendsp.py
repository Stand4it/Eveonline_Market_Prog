import sqlite3
import unittest

from eve_profit import spendsp


def _con(sp, skills=()):
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
    con.execute("CREATE TABLE types(type_id INTEGER, name TEXT)")
    con.execute("CREATE TABLE character_skills(skill_id INTEGER, level INTEGER)")
    con.execute("INSERT INTO meta VALUES('sp_unallocated', ?)", (str(sp),))
    for i, (n, lv) in enumerate(skills, 1):
        con.execute("INSERT INTO types VALUES(?,?)", (i, n))
        con.execute("INSERT INTO character_skills VALUES(?,?)", (i, lv))
    return con


class T(unittest.TestCase):
    def test_step_when_points_are_waiting(self):
        r = spendsp.candidate(_con(100_000, [("Gallente Frigate", 3)]))
        self.assertIn("SPEND YOUR 100,000", r[1])
        self.assertIn("Gallente Hauler to level 1", r[1])
        self.assertNotIn("Gallente Frigate to level 3", r[1])           # already trained
        self.assertIn("Gallente Frigate to level 4", r[1])

    def test_no_step_without_points(self):
        self.assertIsNone(spendsp.candidate(_con(500)))


if __name__ == "__main__":
    unittest.main()
