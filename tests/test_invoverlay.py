import sqlite3
import unittest

from eve_profit import invoverlay as iv


def db():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
    c.execute("CREATE TABLE inventory(type_id INTEGER, system_id INTEGER, quantity INTEGER, PRIMARY KEY(type_id, system_id))")
    c.execute("INSERT INTO inventory VALUES(1,10,33333),(2,10,5)")
    return c


class OverlayTests(unittest.TestCase):
    def test_sold_stack_stays_out_while_esi_is_stale_and_returns_to_truth_when_fresh(self):
        c = db()
        iv.remember_sell_step(c, 10, [(1, 33333)])
        self.assertIn("1 stack", iv.confirm_sold(c))
        self.assertEqual(c.execute("SELECT COUNT(*) FROM inventory WHERE type_id=1").fetchone()[0], 0)
        c.execute("INSERT INTO inventory VALUES(1,10,33333)")            # sync rebuilt from the OLD cached asset list
        iv.after_sync(c)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM inventory WHERE type_id=1").fetchone()[0], 0)
        c.execute("DELETE FROM inventory")                                # later sync: fresh list (different fingerprint) wins
        c.execute("INSERT INTO inventory VALUES(1,10,7)")
        iv.after_sync(c)
        self.assertEqual(c.execute("SELECT quantity FROM inventory WHERE type_id=1").fetchone()[0], 7)

    def test_nothing_to_confirm(self):
        self.assertEqual(iv.confirm_sold(db()), "")


if __name__ == "__main__":
    unittest.main()
