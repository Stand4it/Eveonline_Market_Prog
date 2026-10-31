import sqlite3

from eve_profit import db, esi


class _Esi:
    def __init__(self, ids):
        self.ids = ids

    def region_orders(self, rid, max_pages, log=None):
        return [{"order_id": i, "type_id": 34, "location_id": 60003760, "system_id": 30000142, "is_buy_order": i % 2 == 0, "price": 5.0,
                 "volume_remain": 10, "range": "station"} for i in self.ids]

    def system_kills(self):
        return []

    def get(self, path):
        return [[]]

    def type_info(self, tid):
        return {"name": "Tritanium", "volume": 0.01}


def test_autocommit_scan_writes_a_region_as_a_diff_in_chunks(tmp_path, monkeypatch):
    con = db.connect(str(tmp_path / "x.db"))
    con.execute("INSERT INTO types(type_id,name,volume) VALUES(34,'Tritanium',0.01)")
    con.execute("INSERT INTO orders VALUES(999,34,60003760,30000142,10000002,0,4.0,1,1,'',1.0)")      # gone from the market
    con.execute("INSERT INTO orders VALUES(3,34,60003760,30000142,10000002,1,9.0,10,1,'',1.0)")         # changed price
    con.execute("INSERT INTO orders VALUES(4,34,60003760,30000142,10000002,0,5.0,10,1,'',1.0)")         # unchanged
    con.execute("INSERT INTO orders VALUES(888,34,60008494,30002187,10000043,0,4.0,1,1,'',1.0)")      # another region: untouched
    con.commit()
    con.isolation_level = None
    monkeypatch.setattr(esi, "CHUNK", 3)
    assert esi.refresh_orders(con, _Esi(range(1, 8)), [10000002]) == 7
    ids = {r[0] for r in con.execute("SELECT order_id FROM orders")}
    assert ids == set(range(1, 8)) | {888}
    assert not con.in_transaction
    assert con.execute("SELECT price FROM orders WHERE order_id=3").fetchone()[0] == 5.0
    assert con.execute("SELECT COUNT(*) FROM orders WHERE region_id=10000002 AND fetched_at<10").fetchone()[0] == 0   # all seen now
    assert con.execute("SELECT fetched_at FROM orders WHERE order_id=888").fetchone()[0] == 1.0
