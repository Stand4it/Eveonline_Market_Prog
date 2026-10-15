import json
import sqlite3
import unittest

from eve_profit import along


class KeepCargo(unittest.TestCase):
    def test_cargo_items_are_not_fitted_gear(self):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE fitted(type_id INTEGER, flag TEXT, quantity INTEGER)")
        con.execute("CREATE TABLE types(type_id INTEGER, name TEXT)")
        con.execute("INSERT INTO types VALUES(1,'Cannon X')")
        con.execute("INSERT INTO fitted VALUES(1,'HiSlot0',1)")
        con.execute("INSERT INTO fitted VALUES(1,'Cargo',6)")
        rules = along.keep_rules(con)
        self.assertEqual(rules["cannon x"]["qty"], 1)


if __name__ == "__main__":
    unittest.main()
