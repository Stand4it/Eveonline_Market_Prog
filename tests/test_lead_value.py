import unittest

from eve_profit import agentleads


class LeadValue(unittest.TestCase):
    def test_an_unread_agent_is_worth_the_top_real_option(self):
        self.assertEqual(agentleads._rate({"prior": [1, 2]}, 2_270_000, "Security"), 2_270_000)       # owner rule: unmodeled = the best

    def test_without_any_known_rate_the_prior_is_used(self):
        self.assertGreater(agentleads._rate({"prior": [100_000, 300_000], "runs": 0}, 0, "Security"), 0)


if __name__ == "__main__":
    unittest.main()
