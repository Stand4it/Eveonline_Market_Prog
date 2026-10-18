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


if __name__ == "__main__":
    unittest.main()
