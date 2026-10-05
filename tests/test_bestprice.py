import os, tempfile, unittest
from eve_profit import db
from eve_profit.bestprice import all_regions, best_prices, format_best, resolve_type
from eve_profit.config import Profile
from eve_profit.graph import Graph
from eve_profit.mock import load_mock


def setup():
    con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
    load_mock(con)
    con.execute("UPDATE systems SET region_id=10000002 WHERE system_id>=10")          # a second region
    return con, Graph(con)


class FakeESI:
    def __init__(self, far): self.calls, self.far = [], far
    def paged(self, path, **kw):
        self.calls.append((path, kw))
        rid = int(path.split("/")[2])
        if rid == 10000002:
            return [{"order_id": 1, "location_id": 60000010, "system_id": self.far, "price": 120.0, "volume_remain": 500, "min_volume": 1},
                    {"order_id": 2, "location_id": 60000010, "system_id": self.far, "price": 118.0, "volume_remain": 10000, "min_volume": 1}]
        return [{"order_id": 3, "location_id": 60000001, "system_id": 1, "price": 100.0, "volume_remain": 20000, "min_volume": 1}]


class T(unittest.TestCase):
    def test_resolve_by_name_or_id_and_unknown(self):
        con, g = setup()
        self.assertEqual(resolve_type(con, "tritanium")[:2], (34, "Tritanium"))
        self.assertEqual(resolve_type(con, "34")[1], "Tritanium")
        with self.assertRaises(ValueError):
            resolve_type(con, "Nothing Like This")

    def test_scans_every_region_and_ranks_by_net_with_travel_and_gain_vs_here(self):
        con, g = setup()
        far = [s for s in g.adj if s >= 10 and not g.is_red(s) and g.reach(1, 40).get(s)][0]
        e = FakeESI(far)
        rows, cur = best_prices(con, g, Profile(sales_tax_base=0.02, accounting_level=0), e, 34, 1000)
        self.assertEqual(sorted({int(c[0].split("/")[2]) for c in e.calls}), sorted(all_regions(con)))
        self.assertTrue(all(c[1] == {"order_type": "buy", "type_id": 34} for c in e.calls))
        self.assertEqual(rows[0]["system"], g.name[far])                     # 120 beats 100
        self.assertGreater(rows[0]["jumps"], 0)
        txt = format_best("Tritanium", 1000, rows, "Home")
        self.assertIn("pays", txt)
        self.assertIn("more than Home", txt)

    def test_depth_limits_sellable_units_and_near_equal_prices_say_sell_here(self):
        con, g = setup()
        far = [s for s in g.adj if s >= 10 and not g.is_red(s) and g.reach(1, 40).get(s)][0]

        class Equal(FakeESI):
            def paged(self, path, **kw):
                rows = super().paged(path, **kw)
                for r in rows:
                    r["price"] = 100.0
                return rows
        rows, _ = best_prices(con, g, Profile(), Equal(far), 34, 100000)
        d = next(x for x in rows if x["system"] == g.name[far])
        self.assertEqual(d["units"], 10500)                                   # only 500 + 10000 units have buyers there
        self.assertIn("just sell in Home", format_best("Tritanium", 100000, rows, "Home"))

    def test_a_failing_region_is_skipped(self):
        con, g = setup()

        class Flaky(FakeESI):
            def paged(self, path, **kw):
                if "10000002" in path:
                    raise RuntimeError("boom")
                return super().paged(path, **kw)
        rows, _ = best_prices(con, g, Profile(), Flaky(5), 34, 100)
        self.assertTrue(rows)


if __name__ == "__main__":
    unittest.main()
