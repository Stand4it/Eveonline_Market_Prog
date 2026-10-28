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

    def test_capacitor_stable_or_runs_dry(self):
        self.assertEqual(cc.cap_effect(400, 200, 3.0, 100), (1.0, None))     # 3 GJ/s under the 5 GJ/s recharge
        share, empty = cc.cap_effect(400, 200, 20.0, 300)
        self.assertLess(empty, 300)
        self.assertLess(share, 1.0)
        self.assertEqual(cc.cap_effect(400, 200, 20.0, 10)[0], 1.0)            # a short wave ends before the capacitor is empty

    def test_cap_hungry_repairers_lose_to_a_cap_module_when_cap_is_small(self):
        mods = {"Gun": {"slot": "turret", "dps": 30.0, "cap": 0.0},
                "Rep": {"slot": "low", "tank_add": 60.0, "cap": 5.0}, "Relay": {"slot": "low", "recharge_mult": 0.2}}
        p = SimpleNamespace(combat_dps=20.0, ship_ehp=20000.0, ship_tank_dps=0.0, ship_name="Cat", ships={})
        prices = {"Gun": 1000.0, "Rep": 1000.0, "Relay": 1000.0}
        with mock.patch.object(cc, "modules", return_value=mods), mock.patch.object(cc, "_hull_slots", return_value=("Cat", {"turret": 2, "low": 2})), \
                mock.patch.object(cc, "_fitted_turret_dps", return_value=20.0), \
                mock.patch.object(cc, "hull_cap", return_value={"cap_gj": 100.0, "recharge_s": 200.0, "prop_cap_s": 0.0}), \
                mock.patch.object(cc, "_price", side_effect=lambda con, g, p_, it, q: prices[it] * q):
            bf = cc.best_fit(None, None, p, dict(L1, threat_dps=80.0))
        names = [n for n, _q, _c in bf["items"]]
        self.assertIn("Relay", names)                                          # the repairer only helps with the cap module next to it
        self.assertTrue(bf["passes"])


if __name__ == "__main__":
    unittest.main()
