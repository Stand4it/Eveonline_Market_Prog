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

    def test_acquire_step_gets_a_where_buy_check(self):
        t = ("STEP: ACQUIRE 1 x Salvager I - BUY at Halaima VIII - Moon 17 - Mercantile Club Bureau (about 70,000 ISK)\n"
             "   DO ONLY THIS: dock at Halaima VIII, Market > Salvager I > Buy > the cheapest sell order, 1 unit(s).")
        L = check_lines(t)
        self.assertEqual(len(L), 1)
        self.assertIn('where_buy.py "Salvager I" 1', L[0])

    def test_buy_here_step_names_the_item_in_its_title(self):
        t = ("STEP: BUY 978 x Lead Charge S here (ammo for your guns (Veirainen Naresa's mission))\n"
             "   DO ONLY THIS: Market > search 'Lead Charge S' > Buy 978 at Uedama III (~15 ISK each), then put it straight into your ship.")
        L = check_lines(t)
        self.assertEqual(len(L), 1)
        self.assertIn('where_buy.py "Lead Charge S" 978', L[0])

    def test_item_name_starting_with_a_quote(self):
        t = ("STEP: SELL NOW in Perimeter - about 769,230 ISK\n"
             "   1 x 'Arbalest' Rocket Launcher I       @   769,230.00 each = ~     769,230")
        L = check_lines(t)
        self.assertEqual(len(L), 1)
        self.assertIn('where_sell.py "\'Arbalest\' Rocket Launcher I" 1', L[0])

    def test_other_steps_get_nothing(self):
        self.assertEqual(check_lines("STEP: FLY to Sobaseki\n   DO ONLY THIS: fly"), [])


if __name__ == "__main__":
    unittest.main()
