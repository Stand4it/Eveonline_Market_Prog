import unittest
from types import SimpleNamespace
from unittest import mock

from eve_profit import combatcheck as cc

L1 = dict(cc.LEVEL1)


class CombatCheckTests(unittest.TestCase):
    def test_a_weak_fit_fails_and_a_strong_one_passes(self):
        self.assertFalse(cc.passes(L1, 4.6, 4149, 0))
        self.assertTrue(cc.passes(L1, 200, 8000, 20))

    def test_needed_dps_passes_and_a_bit_less_does_not(self):
        nd, ne = cc.needed(L1, 4.6, 4149, 0)
        self.assertTrue(cc.passes(L1, nd * 1.001, 4149, 0))
        self.assertFalse(cc.passes(L1, nd * 0.95, 4149, 0))
        self.assertIsNone(ne)                                           # 4.6 DPS is under the level's minimum: no EHP fixes that

    def test_numbers_found_by_hull_name_inside_the_ship_name(self):
        p = SimpleNamespace(combat_dps=0, ship_ehp=0, ship_name="Catalyst - Stand4it Dahl", ships={"Catalyst": {"combat_dps": 4.6, "ship_ehp": 4149}})
        self.assertEqual(cc.numbers(p), (4.6, 4149.0, 0.0))

    def test_level_read_from_the_agent_name(self):
        self.assertEqual(cc.level_of(offer={"agent": "Mamdasan Hoghosh (Security, 2, Perimeter II)"}), 2)
        self.assertEqual(cc.level_of(offer={"agent": "Saun Otsusen (Security, L1, Sobaseki)"}), 1)
        self.assertEqual(cc.level_of("combat_anomalies"), "ratting")

    def test_cheapest_passing_fit_uses_owned_modules_free(self):
        mods = {"Gun A": {"slot": "turret", "dps": 10.0}, "Gun B": {"slot": "turret", "dps": 30.0},
                "Rep": {"slot": "low", "tank_add": 10.0}, "Plate": {"slot": "low", "ehp_add": 1000.0}}
        p = SimpleNamespace(combat_dps=20.0, ship_ehp=4000.0, ship_tank_dps=0.0, ship_name="Cat", ships={})
        prices = {"Gun A": 1000.0, "Gun B": 50000.0, "Rep": 5000.0, "Plate": 9000.0}
        with mock.patch.object(cc, "modules", return_value=mods), mock.patch.object(cc, "_hull_slots", return_value=("Cat", {"turret": 8, "low": 2})), \
                mock.patch.object(cc, "_fitted_turret_dps", return_value=20.0), \
                mock.patch.object(cc, "_price", side_effect=lambda con, g, p_, it, q: prices[it] * q):
            bf = cc.best_fit(None, None, p, L1)
        self.assertTrue(bf["passes"])
        self.assertLessEqual(bf["p"], cc.P_MAX)
        cheaper = [x for x in bf["items"]]
        self.assertTrue(cheaper)
        with mock.patch.object(cc, "modules", return_value=mods), mock.patch.object(cc, "_hull_slots", return_value=("Cat", {"turret": 8, "low": 2})), \
                mock.patch.object(cc, "_fitted_turret_dps", return_value=20.0), \
                mock.patch.object(cc, "_price", side_effect=lambda con, g, p_, it, q: 0.0 if it == "Gun B" else prices[it] * q):
            owned = cc.best_fit(None, None, p, L1)
        self.assertLessEqual(owned["cost"], bf["cost"])                  # owning the dear gun makes the passing fit cheaper


if __name__ == "__main__":
    unittest.main()
