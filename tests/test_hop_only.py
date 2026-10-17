import unittest

from eve_profit.haul import hop_only

TXT = """STEP: FLY to Tourier - jump 1 of 1, hauling your stock to Tourier
   3 x Sleeper Data Library
   DO ONLY THIS: load the stock into your ship and fly to Tourier and stop there. Then run  python -m eve_profit next
   ON THE WAY: nothing to buy or sell on this hop.
      going: buy 1 x Kyber Conjunction - Limited at Dodixie (-2,299,000)
      going: sell 1 x Kyber Conjunction - Limited at Jita (+26,917,500)
      going: buy 2 x Thing at Alenia (-100)
      going: trades add 25,113,247 ISK for about 7 more min
   ALSO ON THE ROUTE:
      agent on the route: Annve Hoddoren (Security, Tourier): accept a mission in passing
      agent on the route: Bostiers Oderyncke (Security, Alenia): accept a mission in passing"""


class TestHopOnly(unittest.TestCase):
    def test_any_indent_and_no_second_action(self):
        out = hop_only(TXT.replace("      going:", "   going:").replace("      agent", "   agent"), "Alenia")
        self.assertNotIn("Dodixie", out)
        self.assertNotIn("trades add", out)

    def test_only_this_system_is_kept(self):
        out = hop_only(TXT, "Alenia")
        self.assertNotIn("Dodixie", out)
        self.assertNotIn("Jita", out)
        self.assertNotIn("trades add", out)
        self.assertNotIn("Annve", out)
        self.assertIn("buy 2 x Thing at Alenia", out)
        self.assertIn("Bostiers", out)


if __name__ == "__main__":
    unittest.main()
