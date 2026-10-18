import sqlite3
import unittest

from eve_profit import catalog


class T(unittest.TestCase):
    def test_lp_gate(self):
        a = {"lp_min": 1000}
        self.assertTrue(catalog.missing_for(a, {}, 0.0, 0))
        self.assertFalse(catalog.missing_for(a, {}, 0.0, 5000))
        con = sqlite3.connect(":memory:")
        self.assertEqual(catalog.lp_total(con), 0)
        con.execute("CREATE TABLE lp_balance(corporation_id INTEGER PRIMARY KEY, points INTEGER NOT NULL)")
        con.execute("INSERT INTO lp_balance VALUES(1000419,17500)")             # EverMarks is not LP
        self.assertEqual(catalog.lp_total(con), 0)
        con.execute("INSERT INTO lp_balance VALUES(1000001,2500)")
        self.assertEqual(catalog.lp_total(con), 2500)


if __name__ == "__main__":
    unittest.main()
