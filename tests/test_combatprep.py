import os
import tempfile
import unittest

from eve_profit import combatprep, db
from eve_profit.config import Profile
from eve_profit.graph import Graph
from eve_profit.mock import load_mock


def _hop(system, why, lines):
    return f"HOP {system}"


class CombatPrep(unittest.TestCase):
    def _world(self, ship="Venture"):
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        for tid, name in ((882001, "Venture"), (882002, "Incursus"), (882003, "150mm Carbide Railgun I"), (882004, "Antimatter Charge S"), (882005, "Small Armor Repairer I")):
            con.execute("INSERT OR REPLACE INTO types(type_id,name,volume,group_id) VALUES(?,?,?,1)", (tid, name, 1))
        g = Graph(con)
        p = Profile(current_system="Home", cargo_m3=100, wallet_isk=1e7, current_location_id=60000001, ship_name="x", ship_type_id=882001 if ship == "Venture" else 882002)
        return con, g, p

    def test_wrong_hull_boards_the_owned_combat_frigate_here(self):
        con, g, p = self._world()
        con.execute("INSERT INTO my_ships VALUES(1,882002,1,60000001)")
        self.assertTrue(combatprep.next_step(con, g, p, _hop).startswith("STEP: BOARD your Incursus"))

    def test_wrong_hull_flies_to_the_combat_frigate_elsewhere(self):
        con, g, p = self._world()
        con.execute("INSERT INTO my_ships VALUES(1,882002,2,60000002)")
        self.assertEqual(combatprep.next_step(con, g, p, _hop), "HOP " + g.name[2])

    def test_guns_in_the_hangar_here_are_fitted_first_then_ammo_then_tank(self):
        con, g, p = self._world("Incursus")
        con.execute("INSERT INTO inventory VALUES(882003,1,2)")
        self.assertTrue(combatprep.next_step(con, g, p, _hop).startswith("STEP: FIT 2 x 150mm Carbide Railgun I"))
        con.execute("INSERT INTO fitted VALUES(882003,'HiSlot0',2)")
        con.execute("INSERT INTO inventory VALUES(882004,1,500)")
        self.assertTrue(combatprep.next_step(con, g, p, _hop).startswith("STEP: LOAD 200 x Antimatter Charge S"))

    def test_ready_kit_asks_for_the_fitting_numbers_once(self):
        con, g, p = self._world("Incursus")
        con.execute("INSERT INTO fitted VALUES(882003,'HiSlot0',2)")
        con.execute("INSERT INTO fitted VALUES(882005,'LoSlot0',1)")
        con.execute("INSERT OR REPLACE INTO meta VALUES('cargo_now', ?)", ('{"882004": 300}',))
        self.assertTrue(combatprep.next_step(con, g, p, _hop).startswith("STEP: SHOW ME the fitting window"))
        combatprep.mark_fit_seen(con, "Incursus")
        self.assertEqual(combatprep.next_step(con, g, p, _hop), "")


if __name__ == "__main__":
    unittest.main()
