import sqlite3
import unittest

from eve_profit import invoverlay


def _con():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
    con.execute("CREATE TABLE types(type_id INTEGER, name TEXT)")
    con.execute("CREATE TABLE inventory(type_id INTEGER NOT NULL, system_id INTEGER NOT NULL, quantity INTEGER NOT NULL, PRIMARY KEY(type_id, system_id))")
    con.execute("INSERT INTO types VALUES(7,'Insignia')")
    return con


class T(unittest.TestCase):
    def test_bought_stack_stays_until_esi_catches_up(self):
        con = _con()
        invoverlay.remember_buy_step(con, 1, [(7, 247)])
        self.assertIn("247 x Insignia", invoverlay.confirm_bought(con))
        self.assertEqual(con.execute("SELECT quantity FROM inventory WHERE type_id=7").fetchone()[0], 247)
        con.execute("DELETE FROM inventory")                               # a sync rebuilt the stock from the OLD ESI list (empty)
        invoverlay.after_sync(con)
        self.assertEqual(con.execute("SELECT quantity FROM inventory WHERE type_id=7").fetchone()[0], 247)
        con.execute("DELETE FROM inventory")
        con.execute("INSERT INTO inventory VALUES(7,1,247)")               # ESI now shows the real hangar: it wins, nothing is added twice
        invoverlay.after_sync(con)
        self.assertEqual(con.execute("SELECT quantity FROM inventory WHERE type_id=7").fetchone()[0], 247)


if __name__ == "__main__":
    unittest.main()
