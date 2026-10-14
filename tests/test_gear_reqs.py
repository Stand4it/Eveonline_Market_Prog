import sqlite3
import unittest

from eve_profit import along


class GearReqs(unittest.TestCase):
    def test_miner_ii_needs_mining_iv(self):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE character_skills(skill_id INT, level INT)")
        con.execute("CREATE TABLE type_skills(type_id INT, skill_id INT, level INT)")
        con.execute("INSERT INTO character_skills VALUES(3386,3)")
        self.assertTrue(along._cannot_use(con, "Miner II", 1))
        con.execute("UPDATE character_skills SET level=4")
        self.assertFalse(along._cannot_use(con, "Miner II", 1))


if __name__ == "__main__":
    unittest.main()
