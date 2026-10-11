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
