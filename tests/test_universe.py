import io, json, os, tempfile, unittest, zipfile
from eve_profit import db
from eve_profit.character import sync_character
from eve_profit.config import Profile
from eve_profit.esimap import build_map
from eve_profit.sde_jsonl import import_jsonl


def make_zip(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for name, rows in files.items():
            z.writestr("sde/" + name + ".jsonl", "\n".join(json.dumps(r) for r in rows))


class FakeMapESI:
    """Tiny universe: 1(Jita)-2-3, 3 has gates to 2 and 4."""
    SYS = {1: ("Jita", 0.9, 100, [11]), 2: ("Perimeter", 1.0, 100, [21, 22]),
           3: ("Urlen", 0.8, 100, [31, 32]), 4: ("Far", 0.4, 101, [41])}
    GATE = {11: 2, 21: 1, 22: 3, 31: 2, 32: 4, 41: 3}
    def __init__(self): self.calls = []
    def post_json(self, path, body):
        return {"systems": [{"id": 1, "name": body[0]}]} if body[0] == "Jita" else {}
    def get(self, path, **kw):
        self.calls.append(path)
        kind, ident = path.strip("/").split("/")[1:3]
        ident = int(ident)
        if kind == "systems":
            n, s, c, g = self.SYS[ident]
            return {"name": n, "security_status": s, "constellation_id": c, "stargates": g}, 1
        if kind == "stargates":
            return {"destination": {"system_id": self.GATE[ident]}}, 1
        if kind == "constellations":
            return {"region_id": 9000 + ident}, 1
        raise KeyError(path)


class T(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))

    def test_esimap_depth_and_regions(self):
        s, g = build_map(self.con, FakeMapESI(), "Jita", depth=2, log=lambda *_: None)
        names = {r[0] for r in self.con.execute("SELECT name FROM systems")}
        self.assertEqual(names, {"Jita", "Perimeter", "Urlen"})        # 'Far' is 3 jumps away
        self.assertEqual(self.con.execute("SELECT region_id FROM systems WHERE name='Jita'").fetchone()[0], 9100)
        from eve_profit.graph import Graph
        g = Graph(self.con)
        self.assertEqual(g.route(g.id_of("Jita"), g.id_of("Urlen")).jumps, 2)

    def test_esimap_unknown_system(self):
        with self.assertRaises(RuntimeError):
            build_map(self.con, FakeMapESI(), "Nowhere", depth=1, log=lambda *_: None)

    def test_jsonl_import(self):
        z = os.path.join(tempfile.mkdtemp(), "sde.zip")
        make_zip(z, {
            "mapSolarSystems": [{"_key": 1, "name": {"en": "A"}, "securityStatus": 0.9, "regionID": 5},
                                {"_key": 2, "name": {"en": "B"}, "securityStatus": 0.3, "regionID": 5}],
            "mapStargates": [{"_key": 10, "solarSystemID": 1, "destination": {"solarSystemID": 2, "stargateID": 11}}],
            "npcStations": [{"_key": 60, "solarSystemID": 1, "ownerID": 1000}],
            "groups": [{"_key": 18, "categoryID": 4}],
            "types": [{"_key": 34, "name": {"en": "Tritanium"}, "groupID": 18, "volume": 0.01, "published": True},
                      {"_key": 99, "name": {"en": "Hidden"}, "groupID": 18, "published": False}],
            "blueprints": [{"_key": 500, "activities": {"manufacturing": {
                "materials": [{"typeID": 34, "quantity": 10}], "products": [{"typeID": 600, "quantity": 2}],
                "skills": [{"typeID": 3380, "level": 3}], "time": 600}}}],
            "typeDogma": [{"_key": 34, "dogmaAttributes": [{"attributeID": 182, "value": 3380.0},
                                                            {"attributeID": 277, "value": 2.0}]}],
            "npcCorporations": [{"_key": 1000, "factionID": 500001}],
            "npcCharacters": [{"_key": 3001, "corporationID": 1000, "locationID": 60,
                               "agent": {"agentTypeID": 2, "level": 3}}]})
        n = import_jsonl(self.con, z)
        self.assertEqual((n["systems"], n["gates"], n["stations"], n["types"], n["blueprints"]), (2, 1, 1, 1, 1))
        self.assertEqual(tuple(self.con.execute("SELECT skill_id,level FROM skill_reqs").fetchone()), (3380, 3))
        self.assertEqual(tuple(self.con.execute("SELECT skill_id,level FROM type_skills").fetchone()), (3380, 2))
        self.assertEqual(tuple(self.con.execute("SELECT agent_id,system_id,level FROM agents").fetchone()), (3001, 1, 3))
        self.assertEqual(self.con.execute("SELECT faction_id FROM corp_faction").fetchone()[0], 500001)

    def test_sync_works_before_universe_is_loaded(self):
        class E:
            def get(self, path, **kw):
                d = {"/transactions/": [{"transaction_id": 7, "date": "d", "type_id": 34, "location_id": 60003760,
                                         "unit_price": 5.0, "quantity": 10, "is_buy": True}],
                     "/location/": {"solar_system_id": 30000142}, "/ship/": {"ship_type_id": 1, "ship_name": "T"},
                     "/wallet/": 5.0, "/skills/": {"skills": []}, "/jobs/": [], "/points/": [], "/standings/": [],
                     "/30000142/": {"name": "Jita"}, "/60003760/": {"system_id": 30000142, "owner": 1000, "name": "4-4"}}
                return next(v for k, v in d.items() if path.endswith(k)), 1
            def type_info(self, t): return {"dogma_attributes": [{"attribute_id": 38, "value": 100.0}]}
            def paged(self, path):
                if path.endswith("/blueprints/"):
                    return []
                return [{"type_id": 34, "quantity": 7, "location_id": 60003760, "location_type": "station"}]
        p = Profile()
        r = sync_character(self.con, E(), 1, p)
        self.assertEqual(p.current_system, "Jita")
        self.assertEqual(r["transactions"], 1)
        self.assertEqual(self.con.execute("SELECT unit_price FROM transactions").fetchone()[0], 5.0)
        self.assertEqual(self.con.execute("SELECT quantity FROM inventory").fetchone()[0], 7)
        self.assertEqual(self.con.execute("SELECT corporation_id FROM stations").fetchone()[0], 1000)


if __name__ == "__main__":
    unittest.main()


class FitTests(unittest.TestCase):
    def test_sync_reads_fitted_modules_and_sets_salvager_flag(self):
        from eve_profit.fit import describe_fit
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        con.execute("INSERT INTO types(type_id,name,volume) VALUES(2000,'Small Salvager I',5)")
        con.execute("INSERT INTO types(type_id,name,volume) VALUES(2001,'Small Tractor Beam I',5)")
        con.execute("INSERT INTO systems VALUES(1,'Hek',0.5,1)")

        class E:
            def get(self, path, **kw):
                d = {"/location/": {"solar_system_id": 1, "station_id": 60005686},
                     "/ship/": {"ship_type_id": 652, "ship_name": "M", "ship_item_id": 555},
                     "/wallet/": 1.0, "/skills/": {"skills": []}, "/jobs/": [], "/points/": [], "/standings/": [],
                     "/transactions/": []}
                return next(v for k, v in d.items() if path.endswith(k)), 1
            def type_info(self, t): return {"dogma_attributes": [{"attribute_id": 38, "value": 5500.0}]}
            def paged(self, path):
                if path.endswith("/blueprints/"):
                    return []
                return [{"item_id": 1, "type_id": 2000, "quantity": 1, "location_id": 555, "location_type": "item",
                         "location_flag": "HiSlot0"},
                        {"item_id": 2, "type_id": 2001, "quantity": 1, "location_id": 555, "location_type": "item",
                         "location_flag": "HiSlot1"},
                        {"item_id": 3, "type_id": 34, "quantity": 9, "location_id": 555, "location_type": "item",
                         "location_flag": "Cargo"}]
        p = Profile()
        r = sync_character(con, E(), 1, p)
        self.assertEqual((r["fitted_items"], r["salvager_fitted"], p.can_salvage, p.current_location_id), (3, True, True, 60005686))
        txt = describe_fit(con, p)
        self.assertIn("Small Salvager I", txt)
        self.assertIn("Salvager (salvages wrecks)", txt)
        self.assertIn("Tractor Beam", txt)
