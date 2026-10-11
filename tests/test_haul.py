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
