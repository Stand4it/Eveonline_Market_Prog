import sqlite3
import time
import unittest
from types import SimpleNamespace

from eve_profit import leads


class G:
    name = {1: "Alenia", 2: "Rotonos"}

    def id_of(self, n):
        return {v: k for k, v in self.name.items()}[n]

    def route(self, a, b, *_):
        return SimpleNamespace(jumps=0 if a == b else 3, path=[a, b])


def _con(salvaging=True, ship=True, runs=()):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE types(type_id INTEGER, name TEXT)")
    con.execute("CREATE TABLE character_skills(skill_id INTEGER, level INTEGER)")
    con.execute("CREATE TABLE activity_log(activity TEXT, isk REAL, hours REAL)")
    con.execute("CREATE TABLE my_ships(type_id INTEGER, system_id INTEGER)")
    con.execute("INSERT INTO types VALUES(1,'Salvaging'),(2,'Imicus')")
    if salvaging:
        con.execute("INSERT INTO character_skills VALUES(1,3)")
    if ship:
        con.execute("INSERT INTO my_ships VALUES(2,2)")
    for isk, h in runs:
        con.execute("INSERT INTO activity_log VALUES('Salvage run',?,?)", (isk, h))
    return con


LEAD = [{"system": "Alenia", "activity": "salvaging", "needs": "salvager", "ship_word": "Imicus", "seen": 1000, "life_h": 2, "count": 40, "what": "40 wrecks"}]


class TestLeads(unittest.TestCase):
    def setUp(self):
        self._old = leads.load
        leads.load = lambda: LEAD

    def tearDown(self):
        leads.load = self._old

    def _p(self, here, salv):
        return SimpleNamespace(current_system=here, can_salvage=salv, avoid_yellow=True, wallet_isk=1e7, salvage_wreck_seconds=25.0)

    def test_unknown_is_modeled_at_the_best_rate_minus_travel(self):
        out = leads.candidates(_con(), G(), self._p("Alenia", True), 1_000_000, lambda *a: "FLY", now=1100)
        self.assertEqual(len(out), 1)
        self.assertAlmostEqual(out[0][0], 1_000_000)
        self.assertTrue(out[0][2].startswith("STEP: SALVAGE"))
        self.assertIn("UNKNOWN", out[0][3])

    def test_measured_runs_replace_the_guess(self):
        out = leads.candidates(_con(runs=[(100_000, 1.0), (300_000, 1.0)]), G(), self._p("Alenia", True), 1_000_000, lambda *a: "FLY", now=1100)
        self.assertAlmostEqual(out[0][0], 200_000)

    def test_fetch_the_ship_first_and_charge_the_travel(self):
        out = leads.candidates(_con(), G(), self._p("Alenia", False), 1_000_000, lambda s, w, l: f"STEP: FLY to {s}", now=1100)
        self.assertEqual(out[0][2], "STEP: FLY to Rotonos")
        self.assertLess(out[0][0], 1_000_000)

    def test_expired_lead_is_dropped(self):
        self.assertEqual(leads.candidates(_con(), G(), self._p("Alenia", True), 1e6, lambda *a: "x", now=1000 + 3 * 3600), [])

    def test_no_skill_no_lead(self):
        self.assertEqual(leads.candidates(_con(salvaging=False), G(), self._p("Alenia", True), 1e6, lambda *a: "x", now=1100), [])


if __name__ == "__main__":
    unittest.main()


class TestWaiting(unittest.TestCase):
    def test_blocked_leads_are_listed_not_stepped(self):
        old = leads.load
        leads.load = lambda: [{"system": "Alenia", "activity": "ratting", "needs": "combat", "seen": 1000, "life_h": 24, "what": "hideout"}]
        try:
            self.assertIn("combat-ready", leads.waiting(now=1100)[0])
            self.assertEqual(leads.candidates(_con(), G(), SimpleNamespace(current_system="Alenia", can_salvage=True, avoid_yellow=True, wallet_isk=1e7), 1e6, lambda *a: "x", now=1100), [])
        finally:
            leads.load = old


class TestLookLead(unittest.TestCase):
    def test_unknown_mission_ranks_below_the_best_and_gets_a_dock_step(self):
        con = _con()
        con.execute("CREATE TABLE stations(station_id INTEGER, system_id INTEGER, name TEXT, corporation_id INTEGER)")
        con.execute("INSERT INTO stations VALUES(9, 1, 'Tourier VI - Moon 13 - RSS Assembly Plant', 1)")
        ld = {"system": "Alenia", "station": "Tourier VI - Moon 13", "agent": "Annve", "what": "w", "task_min": 25}
        p = SimpleNamespace(current_system="Alenia", current_location_id=0, avoid_yellow=True)
        c = leads._look_candidate(con, G(), p, ld, 1_000_000, lambda *a: "FLY", 0)
        self.assertLess(c[0], 1_000_000)
        self.assertTrue(c[2].startswith("STEP: DOCK at Tourier VI - Moon 13"))
        p.current_location_id = 9
        self.assertTrue(leads._look_candidate(con, G(), p, ld, 1e6, lambda *a: "FLY", 0)[2].startswith("STEP: OPEN Annve"))
