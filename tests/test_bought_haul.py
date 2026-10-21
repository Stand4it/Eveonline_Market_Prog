import json
import sqlite3
import unittest

from eve_profit import invoverlay


class BoughtStartsTheHaul(unittest.TestCase):
    def test_confirming_a_trade_buy_starts_its_haul_marked_bought(self):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
        con.execute("CREATE TABLE inventory(type_id INTEGER, system_id INTEGER, quantity INTEGER, PRIMARY KEY(type_id, system_id))")
        con.execute("CREATE TABLE types(type_id INTEGER, name TEXT)")
        con.execute("CREATE TABLE systems(system_id INTEGER, name TEXT)")
        con.execute("INSERT INTO types VALUES(7,'Squall SKIN')")
        con.execute("INSERT INTO systems VALUES(1,'Jita')")
        h = {"dest": "Sobaseki", "jumps": 1, "gain": 500000.0, "net": 6500000.0, "items": [("Squall SKIN", 1, 6500000.0, 0.0)], "ore": False}
        invoverlay.remember_buy_step(con, 1, [(7, 1)], haul=h)
        invoverlay.confirm_bought(con)
        hc = json.loads(con.execute("SELECT value FROM meta WHERE key='haul_chain'").fetchone()[0])
        self.assertTrue(hc["bought"])
        self.assertEqual((hc["origin"], hc["dest"]), ("Jita", "Sobaseki"))


if __name__ == "__main__":
    unittest.main()
