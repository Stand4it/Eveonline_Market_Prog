import unittest
from unittest import mock

from eve_profit import agentleads


class LeadValue(unittest.TestCase):
    def test_known_division_uses_the_median_of_real_offers_not_the_best_rate(self):
        with mock.patch.object(agentleads, "observed_rate", lambda d: 180000.0 if d == "Security" else None):
            self.assertEqual(agentleads._rate({"prior": [1, 2]}, 5_000_000, "Security"), 180000.0)
            self.assertEqual(agentleads._rate({"prior": [1, 2]}, 5_000_000, "Unknown"), 5_000_000)   # no data: owner rule, unknown = best


if __name__ == "__main__":
    unittest.main()
