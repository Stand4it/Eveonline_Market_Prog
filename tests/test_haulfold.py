import sqlite3
import time
import unittest

from eve_profit.haulchain import fold_legs


class T(unittest.TestCase):
    def test_fold(self):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE activity_log(id INTEGER PRIMARY KEY AUTOINCREMENT, activity TEXT, isk REAL, hours REAL, ts REAL)")
        now = time.time()
        con.execute("INSERT INTO activity_log(activity,isk,hours,ts) VALUES('Hauling: fly to X',0,1.0,?)", (now,))
        con.execute("INSERT INTO activity_log(activity,isk,hours,ts) VALUES('Market sell stock Jita',3600000,0.5,?)", (now,))
        msg = fold_legs(con, {"t0": now - 10})
        self.assertIn("2,400,000 ISK/hr", msg)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
