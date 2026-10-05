import gzip, json, os, tempfile, unittest
from unittest import mock
from eve_profit import db, zkill
from eve_profit.autopilot import route_alerts
from eve_profit.config import Profile
from eve_profit.graph import Graph
from eve_profit.mock import load_mock
from eve_profit.planner import plan
from eve_profit.risk import route_risk


def setup():
    con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
    load_mock(con)
    return con


class FakeZK:
    def __init__(self): self.paths = []
    def get(self, path):
        self.paths.append(path)
        return [{"killmail_id": 1, "zkb": {"hash": "aa", "totalValue": 5e7}},
                {"killmail_id": 2, "zkb": {"hash": "bb", "totalValue": 3e7}},
                {"killmail_id": 3, "zkb": {"hash": "cc", "totalValue": 9e6}}]


class FakeESI:
    calls = 0
    def get(self, path, **kw):
        FakeESI.calls += 1
        kid = int(path.strip("/").split("/")[1])
        return {"solar_system_id": 2 if kid != 3 else 3, "killmail_time": "2026-10-05T10:00:00Z",
                "victim": {"ship_type_id": 652}}, 1


class T(unittest.TestCase):
    def test_refresh_stores_events_once_and_uses_hauler_groups(self):
        con = setup()
        zk, FakeESI.calls = FakeZK(), 0
        r = zkill.refresh_gank_map(con, zk, FakeESI(), [10000001], log=lambda *_: None)
        self.assertEqual((r["listed"], r["new"], r["kept"]), (3, 3, 3))
        self.assertIn("groupID/28,513", zk.paths[0])
        self.assertIn("regionID/10000001", zk.paths[0])
        self.assertIn(f"pastSeconds/{zkill.WINDOW_S}", zk.paths[0])
        r2 = zkill.refresh_gank_map(con, zk, FakeESI(), [10000001], log=lambda *_: None)
        self.assertEqual((r2["new"], FakeESI.calls), (0, 3))               # killmails are immutable: never re-fetched

    def test_lookup_cap(self):
        con = setup()
        FakeESI.calls = 0
        r = zkill.refresh_gank_map(con, FakeZK(), FakeESI(), [10000001], max_lookups=2, log=lambda *_: None)
        self.assertEqual(r["new"], 2)

    def test_graph_marks_gank_hotspots_and_risk_rises(self):
        con = setup()
        g0 = Graph(con)
        base_risk = route_risk(g0, [1, 2], 1e7)[0]
        con.execute("INSERT INTO gank_events VALUES(1,2,652,1e7,'t',10000001)")
        con.execute("INSERT INTO gank_events VALUES(2,2,652,1e7,'t',10000001)")
        g = Graph(con)
        self.assertTrue(g.is_hot(2))                                       # 2 hauler losses => hotspot
        self.assertGreater(route_risk(g, [1, 2], 1e7)[0], base_risk)
        self.assertIn(("Sys02", "GANKS x2 in 7 days (haulers destroyed here)"), route_alerts(g, [2]))

    def test_away_mode_never_routes_through_gank_hotspots(self):
        con = setup()
        for i in (1, 2):
            con.execute("INSERT INTO gank_events VALUES(?,2,652,1e7,'t',10000001)", (i,))
        p = Profile(max_jumps=3, cargo_m3=5000, wallet_isk=1e9, min_profit_isk=1, away_mode=True,
                    away_max_jumps=6, pickup_jumps=3)
        for o in plan(con, p, 100000, False):
            self.assertNotIn(2, o.waypoints, o.description)

    def test_http_client_sends_user_agent_and_handles_gzip(self):
        body = gzip.compress(json.dumps([{"killmail_id": 9}]).encode())

        class R:
            headers = {"Content-Encoding": "gzip"}
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return body
        seen = {}
        def fake(req, timeout=0):
            seen["ua"], seen["url"] = req.get_header("User-agent"), req.full_url
            return R()
        with mock.patch.object(zkill.urllib.request, "urlopen", fake):
            out = zkill.ZKill(pause=0).get("losses/regionID/1/pastSeconds/3600")
        self.assertEqual(out, [{"killmail_id": 9}])
        self.assertTrue(seen["ua"])
        self.assertTrue(seen["url"].endswith("/"))                         # zKillboard requires the trailing slash


if __name__ == "__main__":
    unittest.main()
