import json
import sqlite3
import unittest
from types import SimpleNamespace

from eve_profit import haulchain


class G:
    name = {1: "Jita", 2: "Sobaseki", 3: "Funtanainen"}

    def id_of(self, n):
        return {v: k for k, v in self.name.items()}[n]

    def route(self, a, b, n=60, avoid=True):
        return SimpleNamespace(jumps={(2, 3): 1}.get((a, b), 1), path=[a, b])


def _con():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
    con.execute("CREATE TABLE types(type_id INTEGER, name TEXT, volume REAL)")
    con.execute("CREATE TABLE orders(order_id INTEGER PRIMARY KEY, type_id INTEGER, location_id INTEGER, system_id INTEGER, region_id INTEGER, is_buy INTEGER, price REAL, volume_remain INTEGER, min_volume INTEGER, issued TEXT, fetched_at REAL)")
    con.execute("CREATE TABLE structures(structure_id INTEGER)")
    con.execute("INSERT INTO types VALUES(7,'Insignia',0.1)")
    con.execute("INSERT INTO orders VALUES(1,7,1047131132102,2,10,1,33330,96,1,'',0)")      # a structure in Sobaseki pays 33,330 for 96
    con.execute("INSERT INTO orders VALUES(2,7,1047131132102,2,10,1,23000,151,1,'',0)")
    con.execute("INSERT INTO meta VALUES('cargo_now', ?)", (json.dumps({"7": 247}),))
    return con


class T(unittest.TestCase):
    def test_sells_here_when_it_beats_carrying_on(self):
        con = _con()
        st = {"dest": "Funtanainen", "items": [["Insignia", 437, 9_903_512.0, 0.0]], "net": 9_903_512.0}
        p = SimpleNamespace(sales_tax=0.075, jump_seconds=60, avoid_yellow=True)
        out = haulchain._sell_here(con, G(), p, st, "Sobaseki")
        self.assertIsNotNone(out)
        net, rows, loc = out
        self.assertEqual(rows[0][1], 247)                                  # the 247 you carry, not the plan's 437
        self.assertEqual(loc, 1047131132102)
        self.assertGreater(net, 6_000_000)

    def test_carries_on_when_here_pays_little(self):
        con = _con()
        con.execute("UPDATE orders SET price=5000")
        st = {"dest": "Funtanainen", "items": [["Insignia", 437, 9_903_512.0, 0.0]], "net": 9_903_512.0}
        p = SimpleNamespace(sales_tax=0.075, jump_seconds=60, avoid_yellow=True)
        self.assertIsNone(haulchain._sell_here(con, G(), p, st, "Sobaseki"))


if __name__ == "__main__":
    unittest.main()
