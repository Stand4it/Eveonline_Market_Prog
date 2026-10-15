import json
import sqlite3
import time
import unittest

from eve_profit import walletdiff


class FakeESI:
    def __init__(self, rows):
        self.rows = rows

    def get(self, path):
        return self.rows, {}


class Late(unittest.TestCase):
    def test_gap_is_explained_by_a_later_sync(self):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
        t0 = time.time() - 600
        con.execute("INSERT INTO meta VALUES('wallet_last', ?)", (json.dumps({"isk": 100.0, "t": t0}),))
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t0 + 60))
        out = walletdiff.report(con, FakeESI([]), 1, 1100.0)
        self.assertIn("not in the journal yet", out)
        rows = [{"date": stamp, "amount": 1000.0, "ref_type": "market_transaction"}]
        out2 = walletdiff.report(con, FakeESI(rows), 1, 1100.0)
        self.assertIn("EXPLAINS THE EARLIER GAP", out2)
        self.assertIn("market sales", out2)


if __name__ == "__main__":
    unittest.main()
