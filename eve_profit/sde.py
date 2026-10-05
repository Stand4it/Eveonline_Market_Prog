"""Import universe (systems, gates, stations, types) from Fuzzwork's SDE sqlite dump.
Download: https://www.fuzzwork.co.uk/dump/latest/sqlite-latest.sqlite.bz2"""
import bz2
import os
import shutil
import sqlite3
import urllib.request

from .config import USER_AGENT

URLS = ["https://www.fuzzwork.co.uk/dump/sqlite-latest.sqlite.bz2",
        "https://www.fuzzwork.co.uk/dump/latest/sqlite-latest.sqlite.bz2"]
MANUAL = ("Could not download the SDE automatically. Manual fix: open https://www.fuzzwork.co.uk/dump/ in a "
          "browser, download sqlite-latest.sqlite.bz2, then run:  python -m eve_profit sde --sde-file "
          "\"C:\\path\\to\\sqlite-latest.sqlite.bz2\"   (a .sqlite file or the .bz2 both work)")
ORE_GROUPS = (450, 451, 452, 453, 454, 455, 456, 457, 458, 459, 460, 461, 462, 467, 468,
              469, 4029, 4030, 4031, 4032, 4033, 4034, 4035, 4036, 4037, 4038)  # approx; refine


def download(dest_dir, url=None):
    """Try the given URL (or known Fuzzwork locations); -> path to extracted .sqlite."""
    os.makedirs(dest_dir, exist_ok=True)
    out = os.path.join(dest_dir, "sde.sqlite")
    errors = []
    for u in ([url] if url else URLS):
        try:
            req = urllib.request.Request(u, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as r, open(out + ".bz2", "wb") as f:
                shutil.copyfileobj(r, f)
            return extract(out + ".bz2", out)
        except Exception as e:           # 404, DNS, proxy...
            errors.append(f"{u}: {e}")
    raise RuntimeError("\n".join(errors) + "\n" + MANUAL)


def extract(src, out):
    """Accept .bz2 or plain sqlite; leave the result at `out`."""
    if src.endswith(".bz2"):
        with bz2.open(src) as s, open(out, "wb") as d:
            shutil.copyfileobj(s, d)
        if os.path.abspath(src) == os.path.abspath(out) + ".bz2":
            os.remove(src)
        return out
    return src


def import_sde(con, sde_path):
    src = sqlite3.connect(sde_path)
    for t in ("systems", "gates", "stations", "types", "agents", "corp_faction"):
        con.execute(f"DELETE FROM {t}")
    con.executemany("INSERT INTO systems VALUES(?,?,?,?)", src.execute(
        "SELECT solarSystemID,solarSystemName,security,regionID FROM mapSolarSystems"))
    con.executemany("INSERT OR IGNORE INTO gates VALUES(?,?)", src.execute(
        "SELECT fromSolarSystemID,toSolarSystemID FROM mapSolarSystemJumps"))
    con.executemany("INSERT INTO stations(station_id,system_id,name,corporation_id) VALUES(?,?,?,?)",
                    src.execute("SELECT stationID,solarSystemID,stationName,corporationID "
                                "FROM staStations"))
    q = ",".join(map(str, ORE_GROUPS))
    con.executemany("INSERT INTO types VALUES(?,?,?,?,?,?)", src.execute(
        f"SELECT t.typeID,t.typeName,t.volume,t.groupID,g.categoryID,"
        f"CASE WHEN t.groupID IN ({q}) THEN 1 ELSE 0 END "
        f"FROM invTypes t LEFT JOIN invGroups g ON g.groupID=t.groupID WHERE t.published=1"))
    for t in ("bp_materials", "bp_products", "skill_reqs", "type_skills"):
        con.execute(f"DELETE FROM {t}")
    _import_skill_reqs(con, src)
    try:  # mission agents (agentTypeID 2 = basic mission agent) and corp -> faction
        con.executemany("INSERT OR IGNORE INTO agents VALUES(?,?,?,?,?,?)", src.execute(
            "SELECT a.agentID,a.corporationID,a.locationID,s.solarSystemID,a.level,a.quality "
            "FROM agtAgents a JOIN staStations s ON s.stationID=a.locationID WHERE a.agentTypeID=2"))
        con.executemany("INSERT OR IGNORE INTO corp_faction VALUES(?,?)", src.execute(
            "SELECT corporationID,factionID FROM crpNPCCorporations WHERE factionID IS NOT NULL"))
    except sqlite3.OperationalError:
        pass
    try:  # manufacturing = activityID 1
        con.executemany("INSERT INTO bp_materials VALUES(?,?,?)", src.execute(
            "SELECT typeID,materialTypeID,quantity FROM industryActivityMaterials "
            "WHERE activityID=1"))
        con.executemany("INSERT OR IGNORE INTO bp_products VALUES(?,?,?,?)", src.execute(
            "SELECT p.typeID,p.productTypeID,p.quantity,COALESCE(a.time,0) "
            "FROM industryActivityProducts p LEFT JOIN industryActivity a "
            "ON a.typeID=p.typeID AND a.activityID=1 WHERE p.activityID=1"))
    except sqlite3.OperationalError:
        pass  # older dump without industry tables
    con.commit()
    return con.execute("SELECT COUNT(*) FROM systems").fetchone()[0]


# dogma attribute ids: requiredSkillN -> its level attribute
SKILL_ATTRS = {182: 277, 183: 278, 184: 279, 1285: 1286, 1289: 1287, 1290: 1288}


def _import_skill_reqs(con, src):
    """Blueprint manufacturing skills + required skills of ships/ores/modules."""
    try:
        con.executemany("INSERT INTO skill_reqs VALUES(?,?,?)", src.execute(
            "SELECT typeID,skillID,level FROM industryActivitySkills WHERE activityID=1"))
        attrs = {}
        for tid, aid, vi, vf in src.execute(
                "SELECT typeID,attributeID,valueInt,valueFloat FROM dgmTypeAttributes "
                "WHERE attributeID IN (%s)" % ",".join(map(str, list(SKILL_ATTRS) + list(SKILL_ATTRS.values())))):
            attrs.setdefault(tid, {})[aid] = int(vi if vi is not None else vf)
        published = {r[0] for r in con.execute("SELECT type_id FROM types")}
        rows = [(tid, a[sa], a[la]) for tid, a in attrs.items() if tid in published
                for sa, la in SKILL_ATTRS.items() if sa in a and la in a]
        con.executemany("INSERT INTO type_skills VALUES(?,?,?)", rows)
    except sqlite3.OperationalError:
        pass
