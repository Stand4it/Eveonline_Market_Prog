import os
import tempfile
import time
import unittest
from unittest import mock

from eve_profit import db, killleads
from eve_profit.config import Profile
from eve_profit.graph import Graph
from eve_profit.mock import load_mock


class KillLeadTests(unittest.TestCase):
    def test_mobile_depot_is_not_a_wreck_and_ship_wreck_says_where(self):
        """owner 2026-10-29: 12 'wrecks' were Mobile Depots, and the step never said where in the system they were."""
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        con.execute("INSERT OR REPLACE INTO types(type_id,name,volume,group_id,category_id) VALUES(33474,'Mobile Depot',50,1246,22)")
        con.execute("INSERT OR REPLACE INTO types(type_id,name,volume,group_id,category_id) VALUES(587,'Rifter',2500,25,6)")
        g = Graph(con)
        p = Profile(current_system="Home", wallet_isk=1e8)
        now = time.time()
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 600))
        kms = {1: 33474, 2: 587}

        def fake_get(url, timeout=10):
            if "zkillboard" in url:
                return [{"killmail_id": 1, "zkb": {"hash": "a", "locationID": 50000001}},
                        {"killmail_id": 2, "zkb": {"hash": "b", "locationID": 50000001}}]
            if "stargates" in url:
                return {"name": "Stargate (Away)"}
            kid = int(url.split("/killmails/")[1].split("/")[0])
            return {"killmail_time": stamp, "victim": {"ship_type_id": kms[kid]}}
        with mock.patch.object(killleads, "_get", side_effect=fake_get), mock.patch.object(killleads, "OUT", os.path.join(tempfile.mkdtemp(), "k.json")):
            leads = killleads.refresh(con, g, p, now=now, max_jumps=0)
        self.assertEqual(leads[0]["count"], 1)
        self.assertNotIn("Mobile Depot", leads[0]["what"])
        self.assertIn("near Stargate (Away)", leads[0]["what"])


if __name__ == "__main__":
    unittest.main()
