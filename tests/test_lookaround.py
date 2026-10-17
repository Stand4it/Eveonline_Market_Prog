import sqlite3
import unittest
from types import SimpleNamespace

from eve_profit import haulchain
import eve_profit.haul as haul


class G:
    def id_of(self, n):
        return 7


def _con():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
    con.execute("CREATE TABLE stations(station_id INTEGER PRIMARY KEY, system_id INTEGER, name TEXT, corporation_id INTEGER)")
    con.execute("INSERT INTO stations VALUES(60001, 7, 'Tourier IV - Some Station', 1)")
    return con


class TestLookAround(unittest.TestCase):
    def setUp(self):
        self._old = haul.agents_here
        haul.agents_here = lambda here, g, p: ["HERE in Tourier: Annve (security): x", "HERE in Tourier: Ongunbjer (security): x"]
        self._cr = haulchain._combat_ready
        haulchain._combat_ready = lambda con, g, p: True

    def tearDown(self):
        haul.agents_here = self._old
        haulchain._combat_ready = self._cr

    def test_dock_first_then_one_agent_per_step_then_fly_on(self):
        con, st = _con(), {"dest": "Jita"}
        p = SimpleNamespace(current_location_id=0)
        t = haulchain._look_around(con, G(), p, st, "Tourier")
        self.assertTrue(t.startswith("STEP: DOCK at Tourier IV - Some Station in Tourier"))
        p.current_location_id = 60001
        t1 = haulchain._look_around(con, G(), p, st, "Tourier")
        self.assertTrue(t1.startswith("STEP: OPEN Annve's offer"))
        self.assertNotIn("Ongunbjer's offer", t1.split("LATER")[0])
        t2 = haulchain._look_around(con, G(), p, st, "Tourier")
        self.assertTrue(t2.startswith("STEP: OPEN Ongunbjer's offer"))
        self.assertEqual(haulchain._look_around(con, G(), p, st, "Tourier"), "")

    def test_security_agents_wait_until_combat_ready(self):
        haulchain._combat_ready = lambda con, g, p: False
        self.assertEqual(haulchain._look_around(_con(), G(), SimpleNamespace(current_location_id=1), {"dest": "Jita"}, "Tourier"), "")


if __name__ == "__main__":
    unittest.main()
