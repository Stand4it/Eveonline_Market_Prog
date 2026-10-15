import sqlite3
import unittest

from eve_profit import dailygoals


class P:
    current_system = "Lirsautton"


class UsableBp(unittest.TestCase):
    def _con(self):
        con = sqlite3.connect(":memory:")
        con.executescript("""
        CREATE TABLE my_blueprints(blueprint_id INT, me INT, te INT, runs INT);
        CREATE TABLE character_skills(skill_id INT, level INT);
        CREATE TABLE skill_reqs(blueprint_id INT, skill_id INT, level INT);
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE stations(station_id INT, system_id INT, name TEXT, corporation_id INT);
        CREATE TABLE structures(structure_id INT, system_id INT);
        CREATE TABLE systems(system_id INT PRIMARY KEY, name TEXT);
        INSERT INTO systems VALUES(1,'Lirsautton'),(2,'Rotonos');
        INSERT INTO my_blueprints VALUES(10,0,0,-1);
        INSERT INTO character_skills VALUES(3380,1);
        """)
        return con

    def test_blueprint_in_another_station(self):
        con = self._con()
        con.execute("INSERT INTO stations VALUES(500,2,'x',1)")
        con.execute("INSERT INTO meta VALUES('bp_locations','{\"10\": 500}')")
        ok, why = dailygoals.usable_blueprint(con, P())
        self.assertFalse(ok)
        self.assertIn("Rotonos", why)

    def test_blueprint_here_and_skills_missing(self):
        con = self._con()
        con.execute("INSERT INTO stations VALUES(501,1,'y',1)")
        con.execute("INSERT INTO meta VALUES('bp_locations','{\"10\": 501}')")
        self.assertTrue(dailygoals.usable_blueprint(con, P())[0])
        con.execute("INSERT INTO skill_reqs VALUES(10,3380,3)")
        self.assertFalse(dailygoals.usable_blueprint(con, P())[0])


if __name__ == "__main__":
    unittest.main()
