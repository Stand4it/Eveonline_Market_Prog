import sqlite3
import unittest
from types import SimpleNamespace

from eve_profit import agentchain


class TestAccepted(unittest.TestCase):
    def test_an_accepted_offer_is_not_offered_for_accepting_again(self):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
        o = {"agent": "Veinalen Elonko (Distribution, L1, X)", "mission": "'The Heiress (2 of 5)': courier", "accepted": "2026-10-21", "to_system": "A"}
        p = SimpleNamespace(current_system="A", avoid_yellow=True)
        text = agentchain.stage_text(con, None, p, o)
        self.assertTrue(text.startswith("STEP: DO Veinalen Elonko's MISSION"), text)


if __name__ == "__main__":
    unittest.main()
