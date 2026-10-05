import os, tempfile, unittest
from eve_profit import db
from eve_profit.combat import find_combat, seed_defaults, standing_ok
from eve_profit.config import Profile
from eve_profit.graph import Graph
from eve_profit.lp import corp_isk_per_lp, find_lp_redemptions, refresh_offers
from eve_profit.mock import load_mock
from eve_profit.orders import load_books


def setup():
    con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
    load_mock(con)
    seed_defaults(con)
    return con, Graph(con)


def prof(**kw):
    d = dict(max_jumps=3, cargo_m3=5000, wallet_isk=1e9, min_profit_isk=1)
    d.update(kw)
    return Profile(**d)


class FakeESI:
    def __init__(self): self.calls = 0
    def get(self, path):
        self.calls += 1
        return [{"offer_id": 9, "type_id": 34, "quantity": 5, "lp_cost": 100, "isk_cost": 10,
                 "required_items": [{"type_id": 35, "quantity": 2}]},
                {"offer_id": 10, "type_id": 34, "quantity": 1, "lp_cost": 1, "ak_cost": 3}], 1


class T(unittest.TestCase):
    def test_rate_and_redemption(self):
        con, g = setup()
        p = prof()
        reach = g.reach(1, 3)
        sells, buys = load_books(con, reach)
        rate = corp_isk_per_lp(con, p, reach, sells, buys, [1000001])[1000001]
        self.assertGreater(rate, 0)
        r = find_lp_redemptions(con, g, p)
        self.assertTrue(r)
        o = r[0]
        self.assertEqual(o.kind, "lp-redeem")
        cost = con.execute("SELECT lp_cost FROM lp_offers WHERE offer_id=?", (o.detail["offer_id"],)).fetchone()[0]
        self.assertLessEqual(o.detail["redemptions"] * cost, 5000)       # never more than the LP you hold
        self.assertFalse([w for w in o.waypoints if g.is_red(w)])

    def test_no_balance_no_redemption_and_wallet_limit(self):
        con, g = setup()
        con.execute("DELETE FROM lp_balance")
        self.assertEqual(find_lp_redemptions(con, g, prof()), [])
        con.execute("INSERT INTO lp_balance VALUES(1000001,5000)")
        con.execute("DELETE FROM lp_offers WHERE offer_id=2")             # the free-ISK offer
        self.assertEqual(find_lp_redemptions(con, g, prof(wallet_isk=10)), [])

    def test_refresh_skips_ak_and_caches_a_day(self):
        con, g = setup()
        con.execute("DELETE FROM lp_offers"); con.execute("DELETE FROM lp_offer_items")
        e = FakeESI()
        self.assertEqual(refresh_offers(con, e, [42]), 1)
        self.assertEqual(refresh_offers(con, e, [42]), 0)               # fetched <24h ago
        self.assertEqual(e.calls, 1)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM lp_offer_items").fetchone()[0], 1)

    def test_mission_uses_agent_and_lp_value(self):
        con, g = setup()
        p = prof(combat_dps=700, ship_ehp=200000, ship_tank_dps=400)
        m = [o for o in find_combat(con, g, p) if "Level 2" in o.description]
        self.assertTrue(m and m[0].detail["agent_id"] == 3001)
        self.assertGreater(m[0].detail["lp_isk_per_hour"], 0)
        con.execute("DELETE FROM agents WHERE level=2")                  # no agent of that level -> no mission
        self.assertFalse([o for o in find_combat(con, g, p) if "Level 2" in o.description])

    def test_standing_gate(self):
        con, g = setup()
        ag = con.execute("SELECT * FROM agents WHERE agent_id=3001").fetchone()
        self.assertTrue(standing_ok(con, ag, 5.0))                       # nothing synced -> assume OK
        con.execute("INSERT INTO standings VALUES(1000001,0.5)")
        self.assertFalse(standing_ok(con, ag, 1.0))
        con.execute("UPDATE standings SET standing=1.5")
        self.assertTrue(standing_ok(con, ag, 1.0))
        p = prof(combat_dps=700, ship_ehp=200000, ship_tank_dps=400)
        con.execute("UPDATE standings SET standing=0")
        self.assertFalse([o for o in find_combat(con, g, p) if "Level 2" in o.description])


if __name__ == "__main__":
    unittest.main()
