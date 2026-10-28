import unittest

from eve_profit import orders


class StationTaxTests(unittest.TestCase):
    def test_half_tax_station_raises_its_bids_inside_the_window_only(self):
        orders._TAX[0] = 0.045
        up = orders._station_uplift("2026-12-01")
        m = up[60008494]
        self.assertAlmostEqual(100 * m * (1 - 0.045), 100 * (1 - 0.0225))   # nets half the tax
        self.assertNotIn(60008494, orders._station_uplift("2026-11-01"))
        self.assertNotIn(60008494, orders._station_uplift("2027-06-01"))


if __name__ == "__main__":
    unittest.main()
