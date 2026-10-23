import sqlite3
import unittest

from eve_profit import invoverlay


class SoldStaysSoldAfterAJump(unittest.TestCase):
    def test_a_sold_stack_that_the_stale_list_moves_with_the_ship_stays_out(self):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
        con.execute("CREATE TABLE inventory(type_id INTEGER, system_id INTEGER, quantity INTEGER, PRIMARY KEY(type_id, system_id))")
        con.execute("CREATE TABLE types(type_id INTEGER, name TEXT)")
        con.execute("INSERT INTO inventory VALUES(7, 1, 1)")             # 1 Miner II in the ship, in system 1
        invoverlay.remember_sell_step(con, 1, [(7, 1)])
        invoverlay.confirm_sold(con)                                     # sold in system 1
        self.assertEqual(con.execute("SELECT COUNT(*) FROM inventory").fetchone()[0], 0)
        con.execute("DELETE FROM inventory")                             # jump: sync rebuilds from the STALE list, cargo now in system 2
        con.execute("INSERT INTO inventory VALUES(7, 2, 1)")
        invoverlay.after_sync(con)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM inventory").fetchone()[0], 0)
        con.execute("DELETE FROM inventory")                             # ESI caught up: the item is really gone
        invoverlay.after_sync(con)
        self.assertIsNone(invoverlay._get(con, "pending_sold"))


if __name__ == "__main__":
    unittest.main()
