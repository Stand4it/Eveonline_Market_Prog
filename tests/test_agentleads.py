import sqlite3
import time
import unittest
from types import SimpleNamespace

from eve_profit import agentleads


class G:
    name = {1: "A", 2: "B", 3: "C"}
    sec = {1: 0.9, 2: 0.8, 3: 0.3}

    def id_of(self, n):
        return {v: k for k, v in self.name.items()}[n]

    def reach(self, cur, n, avoid):
        return {1: SimpleNamespace(jumps=0), 2: SimpleNamespace(jumps=2), 3: SimpleNamespace(jumps=1)}


def _con():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
    con.execute("CREATE TABLE agents(agent_id INTEGER PRIMARY KEY, corporation_id INTEGER, location_id INTEGER, system_id INTEGER, level INTEGER, quality INTEGER, division_id INTEGER, agent_type INTEGER)")
    con.execute("CREATE TABLE standings(from_id INTEGER PRIMARY KEY, standing REAL)")
    con.execute("CREATE TABLE agent_names(agent_id INTEGER PRIMARY KEY, name TEXT)")
    con.execute("CREATE TABLE stations(station_id INTEGER, system_id INTEGER, name TEXT, corporation_id INTEGER)")
    con.execute("INSERT INTO stations VALUES(500,1,'A IV - Plant',1),(501,2,'B II - Depot',1)")
    con.execute("INSERT INTO agents VALUES(10,7,500,1,1,0,35,2),(11,7,500,1,1,0,30,2),(12,7,501,2,2,0,35,2),(13,7,502,3,1,0,35,2),(14,7,500,1,3,0,35,2)")
    return con


def _p(loc=0):
    return SimpleNamespace(current_system="A", avoid_yellow=True, current_location_id=loc)


class TestAgentLeads(unittest.TestCase):
    def test_one_candidate_per_station_below_the_best_rate(self):
        out = agentleads.candidates(_con(), G(), _p(), 1_000_000, lambda s, w, l: f"STEP: FLY to {s}")
        self.assertEqual(len(out), 1)                                   # B's agent is level 2 with no standing; C is unsafe (0.3); level 3 is out
        self.assertLess(out[0][0], 1_000_000)
        self.assertTrue(out[0][2].startswith("STEP: DOCK at A IV - Plant"))

    def test_read_step_when_docked_there_and_once_per_12_hours(self):
        con = _con()
        out = agentleads.candidates(con, G(), _p(500), 1_000_000, lambda *a: "x")
        self.assertTrue(out[0][2].startswith("STEP: READ the agents at A IV - Plant"))
        agentleads.mark_read(con, _p(500))
        self.assertEqual(agentleads.candidates(con, G(), _p(500), 1_000_000, lambda *a: "x"), [])

    def test_level_two_needs_standing(self):
        con = _con()
        con.execute("INSERT INTO standings VALUES(7,2.0)")
        out = agentleads.candidates(con, G(), _p(), 1_000_000, lambda s, w, l: f"STEP: FLY to {s}", limit=5)
        self.assertEqual(len(out), 2)

    def test_here_note_adds_read_to_any_dock_step_once(self):
        con = _con()
        note = agentleads.here_note(con, _p(500))
        self.assertIn("read the agents here", note)
        self.assertEqual(agentleads.here_note(con, _p(500)), "")        # marked read: not repeated
        self.assertEqual(agentleads.here_note(con, _p(0)), "")          # not docked: nothing

    def test_dock_step_also_reads_in_the_same_step(self):
        out = agentleads.candidates(_con(), G(), _p(), 1_000_000, lambda s, w, l: f"STEP: FLY to {s}")
        self.assertIn("ALSO, same stop: read the agents", out[0][2])

    def test_hidden_and_negative_standing_agents_are_not_planned(self):
        con = _con()
        con.execute("INSERT INTO standings VALUES(7,-6.0)")
        self.assertEqual(agentleads.candidates(con, G(), _p(), 1_000_000, lambda *a: "x"), [])
        con.execute("DELETE FROM standings")
        self.assertEqual(agentleads.hide_here(con, _p(500)), 3)
        self.assertEqual(agentleads.candidates(con, G(), _p(), 1_000_000, lambda *a: "x"), [])


if __name__ == "__main__":
    unittest.main()
