import io
import json
import sqlite3
import tarfile

from eve_profit import fitdb

CAT, BLASTER, REP, AMMO = 16240, 561, 3528, 230


def _db():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE types(type_id INTEGER PRIMARY KEY, name TEXT, category_id INTEGER)")
    con.executemany("INSERT INTO types VALUES(?,?,?)", [(CAT, "Catalyst", 6), (670, "Capsule", 6), (BLASTER, "Light Electron Blaster I", 7),
                                                        (REP, "Small Armor Repairer I", 7), (AMMO, "Antimatter Charge S", 8), (3300, "Gunnery", 16)])
    con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
    con.execute("CREATE TABLE prices(type_id INTEGER PRIMARY KEY, adjusted_price REAL)")
    con.execute("CREATE TABLE character_skills(skill_id INTEGER, level INTEGER)")
    con.execute("CREATE TABLE type_skills(type_id INTEGER, skill_id INTEGER, level INTEGER)")
    con.execute("INSERT INTO type_skills VALUES(?,3300,2)", (BLASTER,))
    return con


def _km(i, hull, attackers, items):
    return {"killmail_id": i, "victim": {"ship_type_id": hull, "items": items}, "attackers": attackers}


def _dump(kms):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:bz2") as t:
        for k in kms:
            b = json.dumps(k).encode()
            ti = tarfile.TarInfo(f"killmails/{k['killmail_id']}.json")
            ti.size = len(b)
            t.addfile(ti, io.BytesIO(b))
    return buf.getvalue()


FIT = [{"flag": 27, "item_type_id": BLASTER, "quantity_destroyed": 1}, {"flag": 28, "item_type_id": BLASTER, "quantity_dropped": 1},
       {"flag": 27, "item_type_id": AMMO, "quantity_destroyed": 40}, {"flag": 11, "item_type_id": REP, "quantity_dropped": 1},
       {"flag": 5, "item_type_id": REP, "quantity_dropped": 3}]
NPC = [{"faction_id": 500010, "ship_type_id": 999}]
PLAYER = [{"character_id": 1, "ship_type_id": CAT, "weapon_type_id": BLASTER}]
COPS = [{"corporation_id": fitdb.CONCORD, "ship_type_id": 999}]


def test_parse_counts_fit_by_killer_and_skips_pods_cargo_ammo():
    con = _db()
    blob = _dump([_km(1, CAT, NPC, FIT), _km(2, CAT, PLAYER, FIT), _km(3, CAT, COPS, FIT), _km(4, 670, PLAYER, [])])
    n, k = fitdb.ingest(con, days=1, now=1_800_000_000, fetch=lambda url: blob)
    assert (n, k) == (1, 3)
    fit, npc, pvp, cop = con.execute("SELECT fit, npc, pvp, concord FROM fit_loss").fetchone()
    assert fit == f"{BLASTER}*2 {REP}*1" and (npc, pvp, cop) == (1, 1, 1)          # ammo and cargo are not the fit; the pod is not counted
    assert con.execute("SELECT kills, solo FROM fit_win WHERE ship=? AND weapon=?", (CAT, BLASTER)).fetchone() == (1, 1)   # a pod kill is not a win worth counting
    assert fitdb.ingest(con, days=1, now=1_800_000_000, fetch=lambda url: blob) == (0, 0)   # a day is read once


def test_best_fits_marks_missing_skills():
    con = _db()
    blob = _dump([_km(i, CAT, PLAYER, FIT) for i in range(4)])
    fitdb.ingest(con, days=1, now=1_800_000_000, fetch=lambda url: blob)
    con.execute("INSERT INTO character_skills VALUES(3300, 1)")
    f = fitdb.best_fits(con, CAT)[0]
    assert not f["ok"] and "Gunnery 2 (have 1)" in f["missing"]
    con.execute("UPDATE character_skills SET level=3")
    assert fitdb.best_fits(con, CAT)[0]["ok"]
