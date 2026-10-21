import sqlite3, unittest
from eve_profit import acquire


class _R:
    def __init__(self, j):
        self.jumps = j


class _G:
    sec = {1: 0.9, 2: 0.9}
    name = {1: "A", 2: "B"}

    def id_of(self, n):
        return 1

    def reach(self, cur, mj, ay):
        return {1: _R(0), 2: _R(3)}


class _P:
    current_system = "A"
    avoid_yellow = False


class Sanity(unittest.TestCase):
    def test_stray_expensive_order_dropped(self):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE orders(type_id,system_id,location_id,price,volume_remain,is_buy)")
        con.execute("CREATE TABLE types(type_id,name)")
        con.execute("CREATE TABLE stations(station_id,name)")
        con.execute("CREATE TABLE structures(structure_id,name)")
        con.execute("INSERT INTO types VALUES(1,'Salvager I')")
        con.execute("INSERT INTO orders VALUES(1,1,10,250000,5,0)")
        con.execute("INSERT INTO orders VALUES(1,2,20,54700,5,0)")
        out = acquire.sources(con, _G(), _P(), "Salvager I")
        self.assertEqual(out[0]["system"], "B")


if __name__ == "__main__":
    unittest.main()
