import sqlite3
import unittest
from types import SimpleNamespace

from eve_profit import haulchain


class G:
    name = {1: "A", 2: "B", 3: "C"}

    def id_of(self, n):
        return {"A": 1, "B": 2, "C": 3}[n]

    def route(self, a, b, *_):
        return SimpleNamespace(path=[a, b], jumps=14)


class TestRate(unittest.TestCase):
    def test_rate_counts_the_stock_gain_and_realistic_jump_time(self):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
        st = haulchain.make({"dest": "C", "jumps": 19, "gain": 11_800_000.0, "net": 1_387_500.0, "items": [("X", 3, 1_387_500.0, 0.0)], "extra_isk": 10_000_000.0, "gain_stock": 1_387_500.0}, "A")
        haulchain.save(con, st)
        p = SimpleNamespace(current_system="B", jump_seconds=45.0, avoid_yellow=True, current_location_id=0)
        rate, _ = haulchain.candidate(con, G(), p)
        self.assertLess(rate, 20_000_000)                              # not the 130M ISK/hr a 45 s jump and the optional trades gave
        self.assertGreater(rate, 1_000_000)

    def test_a_haul_whose_stock_was_sold_is_over(self):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
        con.execute("CREATE TABLE types(type_id INTEGER, name TEXT)")
        con.execute("CREATE TABLE transactions(transaction_id, date TEXT, type_id, location_id, unit_price, quantity, is_buy)")
        con.execute("INSERT INTO types VALUES(7,'X')")
        st = haulchain.make({"dest": "C", "jumps": 2, "gain": 1e6, "net": 5e6, "items": [("X", 247, 5e6, 4e6)]}, "A")
        haulchain.save(con, st)
        con.execute("INSERT INTO transactions VALUES(1,'2099-01-01T00:00:00Z',7,0,1.0,247,0)")      # sold all 247 after the haul started
        p = SimpleNamespace(current_system="B", jump_seconds=45.0, avoid_yellow=True, current_location_id=0)
        self.assertIsNone(haulchain.candidate(con, G(), p))
        self.assertIsNone(haulchain.load(con))

    def test_stock_sold_minutes_before_the_haul_was_planned_is_not_hauled(self):
        import time
        iso = lambda s: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - s))   # noqa: E731
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
        con.execute("CREATE TABLE types(type_id INTEGER, name TEXT)")
        con.execute("CREATE TABLE transactions(transaction_id, date TEXT, type_id, location_id, unit_price, quantity, is_buy)")
        con.execute("INSERT INTO types VALUES(7,'X')")
        con.execute("INSERT INTO transactions VALUES(1,?,7,0,1.0,247,1)", (iso(4 * 3600),))      # bought hours ago
        con.execute("INSERT INTO transactions VALUES(2,?,7,0,1.0,247,0)", (iso(300),))           # sold 5 min ago; the stale asset list still showed it
        haulchain.save(con, haulchain.make({"dest": "C", "jumps": 2, "gain": 1e6, "net": 5e6, "items": [("X", 247, 5e6, 4e6)]}, "A"))
        p = SimpleNamespace(current_system="B", jump_seconds=45.0, avoid_yellow=True, current_location_id=0)
        self.assertIsNone(haulchain.candidate(con, G(), p))


if __name__ == "__main__":
    unittest.main()
