import base64, hashlib, json, os, tempfile, time, unittest
from eve_profit import db, sso
from eve_profit.character import sync_character
from eve_profit.config import Profile


def jwt(sub="CHARACTER:EVE:42", name="Pilot"):
    b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{b({'alg':'x'})}.{b({'sub': sub, 'name': name})}.sig"


class FakeESI:
    def get(self, path, **kw):
        d = {"/location/": {"solar_system_id": 2}, "/ship/": {"ship_type_id": 1, "ship_name": "Tank"},
             "/wallet/": 1234.5, "/points/": [{"corporation_id": 1000001, "loyalty_points": 500}], "/standings/": [{"from_id": 3001, "standing": 2.5}], "/jobs/": [{"activity_id": 1, "status": "active"}, {"activity_id": 1, "status": "delivered"}, {"activity_id": 8, "status": "active"}], "/skills/": {"skills": [{"skill_id": 16622, "trained_skill_level": 5}, {"skill_id": 3387, "trained_skill_level": 2}]}}
        return next(v for k, v in d.items() if path.endswith(k)), 1

    def type_info(self, t):
        return {"dogma_attributes": [{"attribute_id": 38, "value": 60000.0}]}

    def paged(self, path):
        if path.endswith("/blueprints/"):
            return [{"type_id": 9, "material_efficiency": 10, "time_efficiency": 20, "runs": -1}]
        return [{"type_id": 34, "quantity": 10, "location_id": 61, "location_type": "station"},
                {"type_id": 34, "quantity": 5, "location_id": 61, "location_type": "station"},
                {"type_id": 35, "quantity": 1, "location_id": 99, "location_type": "other"},
                {"type_id": 36, "quantity": 1, "location_id": 61, "location_type": "station",
                 "is_singleton": True}]


class T(unittest.TestCase):
    def test_pkce(self):
        v, c = sso.make_pkce()
        exp = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(c, exp)
        self.assertNotIn("=", c)

    def test_url_has_pkce_and_scopes(self):
        u = sso.auth_url("cid", "st", "chal")
        for s in ("code_challenge=chal", "S256", "esi-assets.read_assets.v1", "client_id=cid"):
            self.assertIn(s, u)

    def test_refresh_flow(self):
        path = os.path.join(tempfile.mkdtemp(), "t.json")
        json.dump({"character_id": 42, "access_token": "old", "refresh_token": "r",
                   "expires_at": time.time() - 5}, open(path, "w"))
        seen = {}
        def post(d):
            seen.update(d)
            return {"access_token": jwt(), "refresh_token": "r2", "expires_in": 1199}
        tok, cid = sso.get_token("cid", path, post)
        self.assertEqual((seen["grant_type"], cid), ("refresh_token", 42))
        self.assertEqual(json.load(open(path))["refresh_token"], "r2")

    def test_sync(self):
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        con.execute("INSERT INTO systems VALUES(2,'Jita',0.9,1)")
        con.execute("INSERT INTO stations(station_id,system_id,name) VALUES(61,2,'s')")
        p = Profile()
        r = sync_character(con, FakeESI(), 42, p)
        self.assertEqual((p.current_system, p.cargo_m3, p.accounting_level), ("Jita", 60000.0, 5))
        self.assertEqual(con.execute("SELECT quantity FROM inventory").fetchall()[0][0], 15)
        self.assertEqual(r["assets_skipped"], 2)
        self.assertEqual((p.mfg_slots_total, p.mfg_slots_used), (3, 1))   # 1+2 slots, 1 busy job


if __name__ == "__main__":
    unittest.main()


class LoginFlow(unittest.TestCase):
    def _run(self, hits):
        import threading, urllib.request
        from unittest import mock
        path = os.path.join(tempfile.mkdtemp(), "t.json")
        out = {}
        def post(d):
            out["post"] = d
            return {"access_token": jwt(), "refresh_token": "r", "expires_in": 1199}
        def runner():
            try:
                with mock.patch.object(sso.secrets, "token_urlsafe", return_value="STATE"):
                    out["rec"] = sso.login("c" * 32, path, open_browser=False, post=post)
            except Exception as e:
                out["err"] = e
        t = threading.Thread(target=runner); t.start()
        time.sleep(0.5)
        for h in hits:
            try:
                urllib.request.urlopen("http://127.0.0.1:%d%s" % (sso.CALLBACK_PORT, h), timeout=5).read()
            except Exception:
                pass
        t.join(10)
        return out

    def test_callback_ignores_favicon_and_completes(self):
        out = self._run(["/favicon.ico", "/callback?code=ABC&state=STATE"])
        self.assertEqual(out["rec"]["character_id"], 42)
        self.assertEqual(out["post"]["code"], "ABC")

    def test_eve_error_is_reported(self):
        out = self._run(["/callback?error=invalid_scope&error_description=Bad+scope&state=STATE"])
        self.assertIn("Bad scope", str(out["err"]))

    def test_busy_port_is_a_clear_error(self):
        import socket
        s = socket.socket()
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)     # ignore TIME_WAIT from earlier tests
        s.bind(("127.0.0.1", sso.CALLBACK_PORT)); s.listen(1)
        try:
            with self.assertRaises(RuntimeError) as cm:
                sso.login("c" * 32, os.path.join(tempfile.mkdtemp(), "t.json"), open_browser=False)
            self.assertIn("netstat", str(cm.exception))
        finally:
            s.close()


class ESIRetry(unittest.TestCase):
    def test_retries_stalls_but_not_http_errors(self):
        import io, socket, urllib.error
        from unittest import mock
        from eve_profit import esi as E

        class Resp:
            headers = {"X-Pages": "1"}
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, *a): return b"[1]"
        calls = {"n": 0}
        def flaky(req, timeout=0):
            calls["n"] += 1
            if calls["n"] < 3:
                raise socket.timeout("read timed out")
            return Resp()
        with mock.patch.object(E.urllib.request, "urlopen", flaky), mock.patch.object(E.time, "sleep", lambda s: None):
            self.assertEqual(E.ESI().get("/x/")[0], [1])
        self.assertEqual(calls["n"], 3)
        def notfound(req, timeout=0):
            calls["n"] += 1
            raise urllib.error.HTTPError("u", 404, "nf", {}, io.BytesIO(b""))
        calls["n"] = 0
        with mock.patch.object(E.urllib.request, "urlopen", notfound), mock.patch.object(E.time, "sleep", lambda s: None):
            with self.assertRaises(urllib.error.HTTPError):
                E.ESI().get("/x/")
        self.assertEqual(calls["n"], 1)                       # a real 404 is not retried
        def always(req, timeout=0):
            raise socket.timeout("x")
        with mock.patch.object(E.urllib.request, "urlopen", always), mock.patch.object(E.time, "sleep", lambda s: None):
            with self.assertRaises(RuntimeError):
                E.ESI().get("/x/")
