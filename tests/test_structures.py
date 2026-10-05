import os, tempfile, urllib.error, unittest
from eve_profit import db, orders
from eve_profit.config import Profile
from eve_profit.graph import Graph
from eve_profit.mock import load_mock
from eve_profit.orders import load_books, set_structure_haircut
from eve_profit.planner import plan
from eve_profit.structures import refresh_structures


def setup():
    con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
    load_mock(con)
    return con, Graph(con)


class FakeESI:
    def __init__(self): self.paged_calls = []
    def get(self, path, **kw):
        if path == "/universe/structures/":
            return [11, 22, 33], 1
        sid = int(path.split("/")[-2])
        if sid == 22:
            raise urllib.error.HTTPError(path, 403, "no", {}, None)
        return {"name": f"S{sid}", "solar_system_id": 2 if sid == 11 else 5, "owner_id": 1}, 1
    def paged(self, path):
        self.paged_calls.append(path)
        return [{"order_id": 77, "type_id": 34, "is_buy_order": True, "price": 9.0,
                 "volume_remain": 10, "min_volume": 1, "issued": ""}]


class T(unittest.TestCase):
    def tearDown(self):
        orders.STRUCT_BID_HAIRCUT = 0.0

    def test_refresh_denied_remembered_and_orders_only_in_range(self):
        con, g = setup()
        con.execute("DELETE FROM structures"); con.execute("DELETE FROM orders WHERE location_id>1000000000")
        e = FakeESI()
        r = refresh_structures(con, e, {2}, [])                 # only Sys02 in range
        self.assertEqual((r["new_info"], r["denied"], r["orders_fetched"]), (2, 1, 1))
        self.assertEqual(e.paged_calls, ["/markets/structures/11/"])   # 33 is out of range, 22 denied
        row = con.execute("SELECT system_id,location_id FROM orders WHERE order_id=77").fetchone()
        self.assertEqual(tuple(row), (2, 11))
        r2 = refresh_structures(con, e, {2}, [])                # denied one is not retried within a week
        self.assertEqual(r2["denied"], 0)

    def test_orders_replaced_not_duplicated(self):
        con, g = setup()
        con.execute("DELETE FROM structures")                   # drop the mock structure
        e = FakeESI()
        refresh_structures(con, e, {2}, [])
        refresh_structures(con, e, {2}, [])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM orders WHERE location_id=11").fetchone()[0], 1)

    def test_haircut_lowers_structure_bids_only(self):
        con, g = setup()
        p = Profile(structure_sales_tax=0.02, accounting_level=0, sales_tax_base=0.04)   # 4% tax
        set_structure_haircut(p)
        _, buys = load_books(con, {2})
        mine = [b for b in buys[34][2] if b[1] == 500000][0]
        self.assertAlmostEqual(mine[0], 10.0 * (1 - 0.02 / 0.96), places=6)
        orders.STRUCT_BID_HAIRCUT = 0.0
        _, buys = load_books(con, {2})
        self.assertEqual([b for b in buys[34][2] if b[1] == 500000][0][0], 10.0)

    def test_trade_into_structure_found_and_survives_mock_refresh(self):
        from eve_profit.mock import refresh_mock_orders
        con, g = setup()
        refresh_mock_orders(con)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM orders WHERE location_id=1000000000001").fetchone()[0], 1)
        p = Profile(max_jumps=3, cargo_m3=2000, wallet_isk=1e9, min_profit_isk=1)
        o = [x for x in plan(con, p, 100000, False) if x.kind == "trade" and "Tritanium" in x.description
             and "Sys02" in x.description.split("sell @")[-1]]
        self.assertTrue(o)


if __name__ == "__main__":
    unittest.main()
