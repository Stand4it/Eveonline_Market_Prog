"""Import universe (systems, gates, stations, types) from Fuzzwork's SDE sqlite dump.
Download: https://www.fuzzwork.co.uk/dump/latest/sqlite-latest.sqlite.bz2"""
import bz2
import os
import shutil
import sqlite3
import urllib.request

from .config import USER_AGENT

URL = "https://www.fuzzwork.co.uk/dump/latest/sqlite-latest.sqlite.bz2"
ORE_GROUPS = (450, 451, 452, 453, 454, 455, 456, 457, 458, 459, 460, 461, 462, 467, 468,
              469, 4029, 4030, 4031, 4032, 4033, 4034, 4035, 4036, 4037, 4038)  # approx; refine


def download(dest_dir):
    os.makedirs(dest_dir, exist_ok=True)
    out = os.path.join(dest_dir, "sde.sqlite")
    req = urllib.request.Request(URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req) as r, open(out + ".bz2", "wb") as f:
        shutil.copyfileobj(r, f)
    with bz2.open(out + ".bz2") as s, open(out, "wb") as d:
        shutil.copyfileobj(s, d)
    os.remove(out + ".bz2")
    return out


def import_sde(con, sde_path):
    src = sqlite3.connect(sde_path)
    for t in ("systems", "gates", "stations", "types"):
        con.execute(f"DELETE FROM {t}")
    con.executemany("INSERT INTO systems VALUES(?,?,?,?)", src.execute(
        "SELECT solarSystemID,solarSystemName,security,regionID FROM mapSolarSystems"))
    con.executemany("INSERT OR IGNORE INTO gates VALUES(?,?)", src.execute(
        "SELECT fromSolarSystemID,toSolarSystemID FROM mapSolarSystemJumps"))
    con.executemany("INSERT INTO stations VALUES(?,?,?)", src.execute(
        "SELECT stationID,solarSystemID,stationName FROM staStations"))
    q = ",".join(map(str, ORE_GROUPS))
    con.executemany("INSERT INTO types VALUES(?,?,?,?,?,?)", src.execute(
        f"SELECT t.typeID,t.typeName,t.volume,t.groupID,g.categoryID,"
        f"CASE WHEN t.groupID IN ({q}) THEN 1 ELSE 0 END "
        f"FROM invTypes t LEFT JOIN invGroups g ON g.groupID=t.groupID WHERE t.published=1"))
    con.commit()
    return con.execute("SELECT COUNT(*) FROM systems").fetchone()[0]
