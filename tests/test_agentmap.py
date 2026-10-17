import sqlite3
import unittest
from types import SimpleNamespace

from eve_profit import agentmap


class G:
    name = {1: "A", 2: "B", 3: "C", 4: "D"}
    sec = {1: 0.9, 2: 0.8, 3: 0.7, 4: 0.3}

    def id_of(self, n):
        return {v: k for k, v in self.name.items()}[n]

    def reach(self, cur, n, avoid):
        return {1: SimpleNamespace(jumps=0), 2: SimpleNamespace(jumps=1), 3: SimpleNamespace(jumps=2), 4: SimpleNamespace(jumps=3)}

    def route(self, a, b, *_):
        return SimpleNamespace(path=[a, 2, b] if b == 3 else [a, b])


def _con():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE agents(agent_id INTEGER PRIMARY KEY, corporation_id INTEGER, location_id INTEGER, system_id INTEGER, level INTEGER, quality INTEGER, division_id INTEGER, agent_type INTEGER)")
    con.execute("CREATE TABLE standings(from_id INTEGER PRIMARY KEY, standing REAL)")
    con.execute("CREATE TABLE agent_names(agent_id INTEGER PRIMARY KEY, name TEXT)")
    con.execute("CREATE TABLE stations(station_id INTEGER, system_id INTEGER, name TEXT, corporation_id INTEGER)")
    con.execute("INSERT INTO agents VALUES(10,1,500,2,1,0,35,2),(11,1,501,3,2,0,30,2),(12,1,502,4,1,0,35,2),(13,1,503,2,3,0,35,2),(14,1,504,2,1,0,28,2)")
    con.execute("INSERT INTO stations VALUES(500,2,'B IV - Plant',1)")
    con.execute("INSERT INTO standings VALUES(10,1.5),(1,2.0)")
    return con


class TestAgentMap(unittest.TestCase):
    def test_grouped_by_direction_safe_only_and_filtered(self):
        d = agentmap.collect(_con(), G(), SimpleNamespace(current_system="A", avoid_yellow=True), within=5)
        self.assertEqual(set(d), {"B"})                                 # C's agent leaves via B; D is 0.3 (unsafe); level 3 and Manufacturing are out
        names = [(a["system"], a["division"], a["level"]) for a in d["B"]]
        self.assertEqual(names, [("B", "Security", 1), ("C", "Mining", 2)])
        self.assertEqual(d["B"][0]["standing"], 1.5)
        self.assertEqual(d["B"][0]["station"], "B IV - Plant")

    def test_report_asks_for_the_game_data_when_divisions_are_missing(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.execute("CREATE TABLE agents(agent_id INTEGER, system_id INTEGER, level INTEGER)")
        self.assertIn("run  python -m eve_profit universe --force", agentmap.report(con, G(), SimpleNamespace(current_system="A", avoid_yellow=True)))


if __name__ == "__main__":
    unittest.main()


class TestCalibrate(unittest.TestCase):
    def test_division_ids_are_learned_from_known_agents(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
        con.execute("CREATE TABLE agents(agent_id INTEGER PRIMARY KEY, division_id INTEGER)")
        con.execute("INSERT INTO agents VALUES(1,36),(2,36),(3,31),(4,24)")
        orig = agentmap.known_names
        agentmap.known_names = lambda: [("A", "Security"), ("B", "Security"), ("C", "Mining"), ("D", "Distribution")]
        try:
            class E:
                def post_json(self, path, body):
                    return {"characters": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}, {"id": 3, "name": "C"}, {"id": 4, "name": "D"}]}
            self.assertEqual(agentmap.calibrate(con, E()), {36: "Security", 31: "Mining", 24: "Distribution"})
            self.assertEqual(agentmap.get_map(con), {36: "Security", 31: "Mining", 24: "Distribution"})
        finally:
            agentmap.known_names = orig
