import json
import sqlite3
import unittest
from types import SimpleNamespace

from eve_profit import ontheway

OFFER = {"agent": "Bostiers (Security)", "mission": "m", "isk": 1, "bonus": 1, "available": True, "agent_system": "Alenia", "to_system": "Vaere", "cost": [], "where": "x"}


class G:
    name = {1: "Alenia", 2: "Vaere", 3: "Tourier", 4: "Elsewhere"}

    def id_of(self, n):
        return {v: k for k, v in self.name.items()}[n]

    def route(self, a, b, *_):
        paths = {(1, 3): [1, 2, 3], (2, 3): [2, 3]}
        return SimpleNamespace(path=paths.get((a, b), [a, b]), jumps=1)


def _con(chain=None):
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
    if chain:
        con.execute("INSERT INTO meta VALUES('agentchain',?)", (json.dumps(chain),))
    return con


class TestOnTheWay(unittest.TestCase):
    def setUp(self):
        self._o, self._l = ontheway._offers, None
        ontheway._offers = lambda: [OFFER]
        import eve_profit.haulchain as hc
        self.hc, self._load = hc, hc.load
        hc.load = lambda con: {"dest": "Tourier"}

    def tearDown(self):
        ontheway._offers = self._o
        self.hc.load = self._load

    def test_accept_before_leaving_when_the_objective_is_on_the_route(self):
        r = ontheway.step(_con(), G(), SimpleNamespace(current_system="Alenia", avoid_yellow=True))
        self.assertTrue(r[0].startswith("STEP: ACCEPT"))

    def test_do_it_when_passing_through(self):
        r = ontheway.step(_con({"agent": "Bostiers", "stage": "go"}), G(), SimpleNamespace(current_system="Vaere", avoid_yellow=True))
        self.assertTrue(r[0].startswith("STEP: DO"))

    def test_nothing_when_off_route(self):
        ontheway._offers = lambda: [{**OFFER, "to_system": "Elsewhere"}]
        self.assertIsNone(ontheway.step(_con(), G(), SimpleNamespace(current_system="Alenia", avoid_yellow=True)))


if __name__ == "__main__":
    unittest.main()
