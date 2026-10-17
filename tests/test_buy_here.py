import sqlite3
import unittest
from types import SimpleNamespace

from eve_profit.tripplus import buy_here_step

TXT = """STEP: FLY to Pakhshi
   DO ONLY THIS: fly
   ON THE WAY (optional; confirm each buy with `check` first):
      buy 8 x Medium Gremlin Compact Energy Neutralizer at Tar (-2,078,000), sell at Jita (+2,423,500) = +345,500 ISK
      buy 5 x Other at Elsewhere (-1,000), sell at Jita (+2,000) = +1,000 ISK"""


class G:
    def id_of(self, n):
        return 5


def _con():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
    con.execute("CREATE TABLE types(type_id INTEGER, name TEXT)")
    con.execute("CREATE TABLE inventory(type_id INTEGER, system_id INTEGER, quantity INTEGER)")
    con.execute("CREATE TABLE orders(type_id INTEGER, system_id INTEGER, location_id INTEGER, price REAL, is_buy INTEGER, volume_remain INTEGER)")
    con.execute("CREATE TABLE stations(station_id INTEGER, system_id INTEGER, name TEXT, corporation_id INTEGER)")
    con.execute("CREATE TABLE structures(structure_id INTEGER, name TEXT)")
    con.execute("INSERT INTO types VALUES(1,'Medium Gremlin Compact Energy Neutralizer')")
    con.execute("INSERT INTO orders VALUES(1,5,77,259750,0,50)")
    con.execute("INSERT INTO stations VALUES(77,5,'Tar IV - Some Plant',1)")
    return con


class TestBuyHere(unittest.TestCase):
    def test_buy_first_once_and_only_for_this_system(self):
        con, p = _con(), SimpleNamespace(current_system="Tar")
        t = buy_here_step(con, G(), p, TXT)
        self.assertTrue(t.startswith("STEP: ACQUIRE 8 x Medium Gremlin Compact Energy Neutralizer - BUY at Tar IV - Some Plant"))
        self.assertNotIn("Other", t)
        self.assertEqual(buy_here_step(con, G(), p, TXT), "")          # shown once: then the flight


if __name__ == "__main__":
    unittest.main()
