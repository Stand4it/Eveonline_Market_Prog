import unittest

from eve_profit.verify import check_lines


class Verify(unittest.TestCase):
    def test_sell_step_gets_a_where_sell_check_per_item(self):
        t = ("STEP: SELL YOUR HAULED STOCK in Kirras - about 10,945 ISK\n   dock and sell:\n      2 x Ecru Marrow Satin - Limited      ~     10,945\n"
             "   After this `next` chooses the best step.")
        L = check_lines(t)
        self.assertEqual(len(L), 1)
        self.assertIn('where_sell.py "Ecru Marrow Satin - Limited" 2', L[0])

    def test_buy_step_gets_a_where_buy_check(self):
        t = ("STEP: BUY at Jita IV - Moon 4 - Caldari Navy Assembly Plant\n      1 x Squall Shattered Paradigm SKIN\n"
             "   buy 1 x Squall Shattered Paradigm SKIN at 5,998,000 each (5,998,000 ISK)\n   DO ONLY THIS: dock ...")
        L = check_lines(t)
        self.assertEqual(len(L), 1)
        self.assertIn('where_buy.py "Squall Shattered Paradigm SKIN" 1', L[0])

    def test_other_steps_get_nothing(self):
        self.assertEqual(check_lines("STEP: FLY to Sobaseki\n   DO ONLY THIS: fly"), [])


if __name__ == "__main__":
    unittest.main()
