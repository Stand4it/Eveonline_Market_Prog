import os, tempfile, time, unittest
from eve_profit import db
from eve_profit.config import Profile
from eve_profit.contracts import find_contracts, refresh_contracts
from eve_profit.graph import Graph
from eve_profit.mock import load_mock


def setup():
    con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
    load_mock(con)
    return con, Graph(con)


class FakeESI:
    def __init__(self, con): self.calls = []
    def paged(self, path):
        self.calls.append(path)
        if path.startswith("/contracts/public/items/"):
            return [{"type_id": 34, "quantity": 5, "is_included": True}]
        exp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 86400))
        old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 86400))
        return [{"contract_id": 1, "type": "item_exchange", "price": 10, "start_location_id": 60000001,
                 "date_expired": exp},
                {"contract_id": 2, "type": "item_exchange", "price": 10, "start_location_id": 60000001,
                 "date_expired": old},                                     # expired
                {"contract_id": 3, "type": "item_exchange", "price": 10, "start_location_id": 99,
                 "date_expired": exp},                                     # structure: unknown system
                {"contract_id": 4, "type": "item_exchange", "price": 10, "start_location_id": 60000001,
                 "date_expired": exp, "for_corporation": True}]


class T(unittest.TestCase):
    def test_bundle_and_courier_found(self):
        con, g = setup()
        p = Profile(max_jumps=3, cargo_m3=5000, wallet_isk=1e8, min_profit_isk=1)
        r = {o.kind: o for o in find_contracts(con, g, p)}
        self.assertGreater(r["contract"].profit_isk, 0)
        self.assertEqual(r["courier"].profit_isk, 2_500_000)
        for o in r.values():
            self.assertFalse([w for w in o.waypoints if g.is_red(w)])

    def test_courier_needs_cargo_and_collateral(self):
        con, g = setup()
        p = Profile(max_jumps=3, cargo_m3=1000, wallet_isk=1e8, min_profit_isk=1)
        self.assertNotIn("courier", {o.kind for o in find_contracts(con, g, p)})
        p = Profile(max_jumps=3, cargo_m3=5000, wallet_isk=1_000_000, min_profit_isk=1)
        self.assertNotIn("courier", {o.kind for o in find_contracts(con, g, p)})

    def test_too_good_is_flagged(self):
        con, g = setup()
        con.execute("UPDATE contracts SET price=1000 WHERE contract_id=5001")
        p = Profile(max_jumps=3, cargo_m3=5000, wallet_isk=1e8, min_profit_isk=1)
        o = next(o for o in find_contracts(con, g, p) if o.kind == "contract")
        self.assertIn("CHECK-IN-GAME", o.description)

    def test_wants_items_contract_skipped(self):
        con, g = setup()
        con.execute("UPDATE contract_items SET is_included=0 WHERE contract_id=5001")
        p = Profile(max_jumps=3, cargo_m3=5000, wallet_isk=1e8, min_profit_isk=1)
        self.assertNotIn("contract", {o.kind for o in find_contracts(con, g, p)})

    def test_refresh_filters_and_fetches_items(self):
        con, g = setup()
        con.execute("DELETE FROM contracts"); con.execute("DELETE FROM contract_items")
        e = FakeESI(con)
        stored, fetched = refresh_contracts(con, e, [10000001], {1})
        self.assertEqual((stored, fetched), (1, 1))     # expired, structure, corp dropped
        self.assertEqual(con.execute("SELECT quantity FROM contract_items").fetchone()[0], 5)


if __name__ == "__main__":
    unittest.main()
