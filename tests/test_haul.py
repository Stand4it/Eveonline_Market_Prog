import unittest



class ShipLinesTests(unittest.TestCase):
    def test_ship_and_fit_lines(self):
        from eve_profit import haul
        from eve_profit.db import connect
        from eve_profit.config import Profile
        con = connect(":memory:")
        con.execute("INSERT INTO types(type_id,name,volume,capacity) VALUES(1,'Expanded Cargohold I',5,0)")
        con.execute("INSERT INTO inventory VALUES(1,7,1)")

        class G:
            def id_of(self, n):
                return 7
        p = Profile(ship_name="Imicus", cargo_m3=400.0, current_system="Rotonos")
        out = "\n".join(haul.ship_lines(con, G(), p, {"other_m3": 12.0, "ore": False}))
        self.assertIn("SHIP: your Imicus", out)
        self.assertIn("FIT 1 x Expanded Cargohold I", out)

    def test_flex_gear_listed(self):
        from eve_profit import haul
        from eve_profit.db import connect
        from eve_profit.config import Profile
        con = connect(":memory:")
        con.execute("INSERT INTO types(type_id,name,volume,capacity) VALUES(2,'Civilian Miner',5,0)")
        con.execute("INSERT INTO inventory VALUES(2,7,1)")

        class G:
            def id_of(self, n):
                return 7
        out = "\n".join(haul.ship_lines(con, G(), Profile(ship_name="Imicus", cargo_m3=400.0, current_system="Rotonos"), {"other_m3": 1.0}))
        self.assertIn("KEEP FLEXIBLE: 1 x Civilian Miner", out)


class HopOnlyTests(unittest.TestCase):
    def test_only_the_hop_is_left(self):
        from eve_profit.haul import hop_only
        t = ("STEP: FLY to Tiberis - jump 1 of 18, hauling your stock to Jita\n"
             "           2 x Entropic Rose    1,152,550 there vs          0 here\n"
             "   1 trip(s), about 16 min, +1,503,032 ISK more\n"
             "   DO ONLY THIS: fly to Tiberis and stop there. Then run  python -m eve_profit next  (it plans again from there: 18 jumps left to Jita, no planned trip back).\n"
             "   AT Jita after selling: next best\n")
        o = hop_only(t)
        self.assertNotIn("Jita", o)
        self.assertIn("STEP: FLY to Tiberis", o)
        self.assertIn("2 x Entropic Rose", o)
        self.assertNotIn("there vs", o)


class DestinationTests(unittest.TestCase):
    def test_destination_of_a_fly_step(self):
        from eve_profit.autopilot import destination_of
        self.assertEqual(destination_of("STEP: FLY to Tiberis\n   DO ONLY THIS: x"), "Tiberis")
        self.assertEqual(destination_of(">> STEP: FLY to Tiberis - jump 1 of 18, hauling your stock to Jita"), "Tiberis")
        self.assertIsNone(destination_of("STEP: SELL Scordite"))


class AgentsNearTests(unittest.TestCase):
    def test_distance_is_recomputed_from_here(self):
        from eve_profit.haul import agents_near

        class R:
            def __init__(self, j):
                self.jumps = j

        class G:
            ids = {"Tiberis": 1, "Rotonos": 2, "Axiosere": 3}

            def id_of(self, n):
                return self.ids[n]

            def route(self, a, b, mx, yellow):
                return R(1 if {a, b} == {1, 2} else 2)

        class P:
            avoid_yellow = True
        out = agents_near(G(), P(), "Tiberis")
        self.assertTrue(any(l.startswith("1 jump away in Rotonos") for l in out))
        self.assertTrue(any("Axiosere" in l and "2 jumps away" in l for l in out))


class HopOnlyChainTests(unittest.TestCase):
    def test_chain_item_line_loses_price_and_destination(self):
        from eve_profit.haul import hop_only
        o = hop_only("STEP: FLY to Fortitude\n           2 x Entropic Rose Metallic - Limited ~  1,152,550 at Jita\n")
        self.assertNotIn("Jita", o)
        self.assertIn("2 x Entropic Rose Metallic - Limited", o)


class HopOnlyElsewhereTests(unittest.TestCase):
    def test_trades_at_other_systems_are_not_in_this_step(self):
        from eve_profit.haul import hop_only
        t = ("STEP: FLY to Fortitude\n   DO ONLY THIS: fly to Fortitude and stop there.\n"
             "   ON THE WAY (optional; confirm each buy with `check` first):\n"
             "      buy 2 x Ferros at Kemerk (-1,378,000), sell at Jita (+2,590,000) = +1,212,000 ISK\n"
             "   ALSO ON THE ROUTE:\n      need anyway: 3 x Miner I is ~12,000 each at Manifest on the route (here 25,000): buy there\n")
        o = hop_only(t, "Tiberis")
        self.assertNotIn("Kemerk", o)
        self.assertNotIn("Manifest", o)
        self.assertNotIn("ALSO ON THE ROUTE", o)
        o2 = hop_only(t, "Kemerk")
        self.assertIn("Kemerk", o2)


class ThreadsTests(unittest.TestCase):
    def test_best_per_thread(self):
        from eve_profit.nextstep import _threads
        t = _threads([(5e6, "haul stock to Jita", "x", ""), (1e6, "best trade A", "x", ""), (2e6, "AIR daily goals", "x", ""), (float("inf"), "update the model from the game", "x", "")])
        self.assertEqual(t["ISK: trading and hauling"][0], 5e6)
        self.assertIn("AIR career and agent missions", t)
        self.assertIn("teaching the model", t)
