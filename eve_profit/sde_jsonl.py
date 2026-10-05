"""Import CCP's official SDE (JSON Lines zip) into our tables.
Download: https://developers.eveonline.com/static-data/eve-online-static-data-latest-jsonl.zip
Written without network access: field names are read tolerantly (.get with fallbacks) and the
import prints how many rows each file produced, so a layout change shows up immediately.
Integer-keyed datasets are lists of objects with `_key` (and either the fields inline or `_value`)."""
import json
import os
import shutil
import urllib.request
import zipfile

from .config import USER_AGENT

URL = "https://developers.eveonline.com/static-data/eve-online-static-data-latest-jsonl.zip"
SKILL_ATTRS = {182: 277, 183: 278, 184: 279, 1285: 1286, 1289: 1287, 1290: 1288}


def download(dest_dir, url=URL):
    os.makedirs(dest_dir, exist_ok=True)
    out = os.path.join(dest_dir, "sde-jsonl.zip")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=300) as r, open(out, "wb") as f:
        shutil.copyfileobj(r, f)
    return out


def _name(x):
    if isinstance(x, dict):
        return x.get("en") or next(iter(x.values()), "")
    return x or ""


def _rows(zf, base):
    """Yield dict rows of `<base>.jsonl` wherever it sits in the zip; [] if absent."""
    member = next((n for n in zf.namelist() if n.split("/")[-1].lower() == base.lower() + ".jsonl"), None)
    if not member:
        return
    with zf.open(member) as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def import_jsonl(con, zip_path):
    """-> dict of row counts per table."""
    zf = zipfile.ZipFile(zip_path)
    for t in ("systems", "gates", "stations", "types", "agents", "corp_faction",
              "bp_materials", "bp_products", "skill_reqs", "type_skills"):
        con.execute(f"DELETE FROM {t}")
    n = {}
    cat = {r["_key"]: r.get("categoryID") for r in _rows(zf, "groups")}
    con.executemany("INSERT OR IGNORE INTO systems VALUES(?,?,?,?)",
                    [(r["_key"], _name(r.get("name")), r.get("securityStatus", r.get("security", 0.0)),
                      r.get("regionID", 0)) for r in _rows(zf, "mapSolarSystems")])
    n["systems"] = con.execute("SELECT COUNT(*) FROM systems").fetchone()[0]
    for r in _rows(zf, "mapStargates"):
        dest = (r.get("destination") or {}).get("solarSystemID")
        if dest and r.get("solarSystemID"):
            con.execute("INSERT OR IGNORE INTO gates VALUES(?,?)", (r["solarSystemID"], dest))
    n["gates"] = con.execute("SELECT COUNT(*) FROM gates").fetchone()[0]
    con.executemany("INSERT OR IGNORE INTO stations(station_id,system_id,name,corporation_id) VALUES(?,?,?,?)",
                    [(r["_key"], r.get("solarSystemID"), _name(r.get("name")), r.get("ownerID"))
                     for r in _rows(zf, "npcStations") if r.get("solarSystemID")])
    n["stations"] = con.execute("SELECT COUNT(*) FROM stations").fetchone()[0]
    con.executemany("INSERT OR IGNORE INTO types(type_id,name,volume,group_id,category_id,is_ore,capacity) "
                    "VALUES(?,?,?,?,?,0,?)",
                    [(r["_key"], _name(r.get("name")), r.get("volume", 1) or 1, r.get("groupID"),
                      cat.get(r.get("groupID")), r.get("capacity", 0) or 0)
                     for r in _rows(zf, "types") if r.get("published", True)])
    n["types"] = con.execute("SELECT COUNT(*) FROM types").fetchone()[0]
    for r in _rows(zf, "blueprints"):
        m = (r.get("activities") or {}).get("manufacturing") or {}
        prods = m.get("products") or []
        if not prods:
            continue
        for x in m.get("materials", []):
            con.execute("INSERT OR IGNORE INTO bp_materials VALUES(?,?,?)", (r["_key"], x["typeID"], x["quantity"]))
        con.execute("INSERT OR IGNORE INTO bp_products VALUES(?,?,?,?)",
                    (r["_key"], prods[0]["typeID"], prods[0]["quantity"], m.get("time", 0)))
        for s in m.get("skills", []):
            con.execute("INSERT INTO skill_reqs VALUES(?,?,?)", (r["_key"], s["typeID"], s["level"]))
    n["blueprints"] = con.execute("SELECT COUNT(*) FROM bp_products").fetchone()[0]
    published = {x[0] for x in con.execute("SELECT type_id FROM types")}
    rows = []
    for r in _rows(zf, "typeDogma"):
        if r["_key"] not in published:
            continue
        raw = {x["attributeID"]: x["value"] for x in r.get("dogmaAttributes", [])}
        if 38 in raw and raw[38]:
            con.execute("UPDATE types SET capacity=? WHERE type_id=? AND capacity=0", (raw[38], r["_key"]))
        if 275 in raw:                                    # skillTimeConstant = rank; 180/181 = training attributes
            con.execute("UPDATE types SET skill_rank=?,skill_primary=?,skill_secondary=? WHERE type_id=?",
                        (raw[275], int(raw.get(180, 0)), int(raw.get(181, 0)), r["_key"]))
        a = {k: int(v) for k, v in raw.items() if k in SKILL_ATTRS or k in SKILL_ATTRS.values()}
        rows += [(r["_key"], a[s], a[l]) for s, l in SKILL_ATTRS.items() if s in a and l in a]
    con.executemany("INSERT INTO type_skills VALUES(?,?,?)", rows)
    n["type_skills"] = len(rows)
    con.executemany("INSERT OR IGNORE INTO corp_faction VALUES(?,?)",
                    [(r["_key"], r["factionID"]) for r in _rows(zf, "npcCorporations") if r.get("factionID")])
    st = {r[0]: r[1] for r in con.execute("SELECT station_id,system_id FROM stations")}
    for r in _rows(zf, "npcCharacters"):
        ag = r.get("agent")
        if ag and r.get("locationID") in st and ag.get("agentTypeID", 2) == 2:
            con.execute("INSERT OR IGNORE INTO agents VALUES(?,?,?,?,?,?)",
                        (r["_key"], r.get("corporationID"), r["locationID"], st[r["locationID"]],
                         ag.get("level", 1), 0))
    n["agents"] = con.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
    con.commit()
    return n
