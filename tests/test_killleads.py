import json
import os
import tempfile
import unittest
from unittest import mock

from eve_profit import leads


class AutoLeads(unittest.TestCase):
    def test_killboard_leads_join_the_reported_ones_and_expire(self):
        d = tempfile.mkdtemp()
        auto, own = os.path.join(d, "kill_leads.json"), os.path.join(d, "leads.json")
        json.dump({"leads": [{"id": "a", "system": "X", "activity": "salvaging", "seen": 1, "life_h": 2, "count": 3}]}, open(auto, "w"))
        json.dump({"leads": [{"id": "b", "system": "Y", "activity": "salvaging", "seen": 1, "life_h": 2, "count": 1}]}, open(own, "w"))
        with mock.patch.object(leads, "_AUTO", auto), mock.patch.object(leads, "_FILE", own):
            self.assertEqual({x["id"] for x in leads.load()}, {"a", "b"})


if __name__ == "__main__":
    unittest.main()
