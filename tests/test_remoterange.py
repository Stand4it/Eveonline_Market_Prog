import sqlite3
import unittest
from types import SimpleNamespace

from eve_profit import remoterange


class G:
    adj = {1: [2], 2: [1, 3], 3: [2, 4], 4: [3]}
    sec = {1: 0.9, 2: 0.9, 3: 0.9, 4: 0.3}
    name = {1: "A", 2: "B", 3: "C", 4: "D"}
    region = {1: 7, 2: 7, 3: 7, 4: 8}


def _con():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE orders(order_id INTEGER PRIMARY KEY, type_id INTEGER, location_id INTEGER, system_id INTEGER, region_id INTEGER, is_buy INTEGER, price REAL, volume_remain INTEGER, min_volume INTEGER, issued TEXT, fetched_at REAL)")
    return con


class T(unittest.TestCase):
    def test_order_in_range_pays_without_travel(self):
        con = _con()
        con.execute("INSERT INTO orders VALUES(1,50,900,3,7,1,1000000,5,1,'',0)")       # C, 2 jumps from A, range 40, same region
        con.execute("INSERT INTO orders VALUES(2,50,901,3,7,1,2000000,5,1,'',0)")       # C, range 1: too short
        con.execute("INSERT INTO orders VALUES(3,50,902,4,8,1,3000000,5,1,'',0)")       # D, low-sec: ignored
        remoterange.store(con, [{"order_id": 1, "range": "40", "is_buy_order": True}, {"order_id": 2, "range": "1", "is_buy_order": True}, {"order_id": 3, "range": "region", "is_buy_order": True}])
        rb = remoterange.remote_bid(con, G(), 50, 1, 1, 800, 0.075)
        self.assertEqual((rb["system"], rb["jumps"]), ("C", 2))
        self.assertAlmostEqual(rb["net"], 925000.0)

    def test_another_region_is_never_reachable(self):
        con = _con()
        con.execute("INSERT INTO orders VALUES(1,50,900,3,8,1,1000000,5,1,'',0)")       # C is in region 8 here, you are in region 7
        remoterange.store(con, [{"order_id": 1, "range": "40", "is_buy_order": True}])
        g = G()
        g.region = {1: 7, 2: 7, 3: 8, 4: 8}
        self.assertIsNone(remoterange.remote_bid(con, g, 50, 1, 1, 800, 0.075))

    def test_station_range_does_not_reach(self):
        con = _con()
        con.execute("INSERT INTO orders VALUES(1,50,900,2,7,1,1000000,5,1,'',0)")
        remoterange.store(con, [{"order_id": 1, "range": "station", "is_buy_order": True}])
        self.assertIsNone(remoterange.remote_bid(con, G(), 50, 1, 1, 800, 0.075))


if __name__ == "__main__":
    unittest.main()
