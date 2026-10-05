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
             "/wallet/": 1234.5, "/skills/": {"skills": [{"skill_id": 16622, "trained_skill_level": 5}]}}
        return next(v for k, v in d.items() if path.endswith(k)), 1

    def type_info(self, t):
        return {"dogma_attributes": [{"attribute_id": 38, "value": 60000.0}]}

    def paged(self, path):
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
        con.execute("INSERT INTO stations VALUES(61,2,'s')")
        p = Profile()
        r = sync_character(con, FakeESI(), 42, p)
        self.assertEqual((p.current_system, p.cargo_m3, p.accounting_level), ("Jita", 60000.0, 5))
        self.assertEqual(con.execute("SELECT quantity FROM inventory").fetchall()[0][0], 15)
        self.assertEqual(r["assets_skipped"], 2)


if __name__ == "__main__":
    unittest.main()
