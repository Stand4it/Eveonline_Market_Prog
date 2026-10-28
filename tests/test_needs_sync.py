import unittest

from eve_profit.nextstep import finish_block, needs_sync


class NeedsSync(unittest.TestCase):
    def test_kinds(self):
        for s in ("STEP: FLY to Tunttaras", "STEP: DOCK at Jita 4-4", "STEP: SHOW ME A SCREEN - x", "STEP: READ the agents at y"):
            self.assertFalse(needs_sync(s), s)
        for s in ("STEP: BUY 7 x Light Electron Blaster I", "STEP: SELL NOW in Jita", "STEP: ACCEPT the mission", "STEP: SOMETHING NEW"):
            self.assertTrue(needs_sync(s), s)

    def test_block_has_one_command(self):
        fly = finish_block("STEP: FLY to Tunttaras\n   DO ONLY THIS: fly there.")
        self.assertIn("eve_profit stop ", fly); self.assertNotIn("stopsync", fly); self.assertNotIn("eve_profit now", fly)
        buy = finish_block("STEP: BUY 1 x Small Armor Repairer I\n   in Jita")
        self.assertIn("eve_profit stopsync", buy); self.assertNotIn("eve_profit sync ", buy); self.assertNotIn("eve_profit now", buy)


if __name__ == "__main__":
    unittest.main()
