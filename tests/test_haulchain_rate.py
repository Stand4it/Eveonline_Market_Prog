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


if __name__ == "__main__":
    unittest.main()
