"""Pull your character state from ESI and update the profile + inventory."""
ACCOUNTING = 16622
INDUSTRY, ADV_INDUSTRY = 3380, 3388
MASS_PRODUCTION, ADV_MASS_PRODUCTION = 3387, 24625
CAPACITY_ATTR = 38


def _type(esi, tid):
    return esi.type_info(tid)


def _hull_cargo_bonus(con, ship_type_id, skills):
    """Racial industrial hulls get +5% cargo per level of their Industrial skill."""
    for r in con.execute("SELECT s.skill_id,t.name FROM type_skills s JOIN types t ON t.type_id=s.skill_id "
                         "WHERE s.type_id=?", (ship_type_id,)):
        if r["name"].endswith(("Industrial", "Hauler")):
            lvl = next((x["trained_skill_level"] for x in skills if x["skill_id"] == r["skill_id"]), 0)
            return 1 + 0.05 * lvl
    return 1.0


def _fill_capacity(con, esi, type_id):
    """Hull hold size from ESI (dogma attribute 38) when the SDE import didn't provide it."""
    r = con.execute("SELECT capacity FROM types WHERE type_id=?", (type_id,)).fetchone()
    if r is None or r[0]:
        return
    try:
        cap = next((x["value"] for x in esi.type_info(type_id).get("dogma_attributes", [])
                    if x["attribute_id"] == CAPACITY_ATTR), 0)
    except Exception:
        return
    con.execute("UPDATE types SET capacity=? WHERE type_id=?", (cap, type_id))


def _is_ship(con, esi, type_id):
    """Category 6 = ships. Unknown category (no SDE) is looked up once from ESI."""
    r = con.execute("SELECT category_id,group_id FROM types WHERE type_id=?", (type_id,)).fetchone()
    if r is None:
        return False
    if r[0] is None and r[1]:
        try:
            cat = esi.get(f"/universe/groups/{r[1]}/")[0]["category_id"]
            con.execute("UPDATE types SET category_id=? WHERE group_id=?", (cat, r[1]))
            return cat == 6
        except Exception:
            return False
    return r[0] == 6


def _sync_attributes_and_queue(con, esi, cid):
    """Training attributes + skill queue (queue needs esi-skills.read_skillqueue.v1: skipped if not granted)."""
    try:
        at = esi.get(f"/characters/{cid}/attributes/")[0]
        con.execute("DELETE FROM char_attrs")
        con.executemany("INSERT INTO char_attrs VALUES(?,?)",
                        [(k, at[k]) for k in ("charisma", "intelligence", "memory", "perception", "willpower") if k in at])
    except Exception:
        pass
    con.execute("DELETE FROM skill_queue")
    try:
        q = esi.get(f"/characters/{cid}/skillqueue/")[0]
        con.executemany("INSERT INTO skill_queue VALUES(?,?,?,?)",
                        [(x["queue_position"], x["skill_id"], x["finished_level"], x.get("finish_date")) for x in q])
    except Exception:
        pass


def sync_character(con, esi, cid, profile):
    """Fills profile (system, ship, cargo, wallet, tax) and inventory. -> summary dict."""
    loc = esi.get(f"/characters/{cid}/location/")[0]
    ship = esi.get(f"/characters/{cid}/ship/")[0]
    wallet = esi.get(f"/characters/{cid}/wallet/")[0]
    skills = esi.get(f"/characters/{cid}/skills/")[0]["skills"]
    row = con.execute("SELECT name FROM systems WHERE system_id=?",
                      (loc["solar_system_id"],)).fetchone()
    if row:
        profile.current_system = row[0]
    else:                    # universe not loaded yet: ask ESI for the name
        profile.current_system = esi.get(f"/universe/systems/{loc['solar_system_id']}/")[0]["name"]
    profile.ship_name = ship.get("ship_name", profile.ship_name)
    profile.ship_type_id = ship["ship_type_id"]
    cap = next((a["value"] for a in _type(esi, ship["ship_type_id"]).get("dogma_attributes", [])
                if a["attribute_id"] == CAPACITY_ATTR), None)
    if cap:
        profile.cargo_m3 = cap * _hull_cargo_bonus(con, ship["ship_type_id"], skills)
    profile.wallet_isk = wallet
    lvl = next((s["trained_skill_level"] for s in skills if s["skill_id"] == ACCOUNTING), 0)
    profile.accounting_level = lvl
    lv = lambda sid: next((s["trained_skill_level"] for s in skills if s["skill_id"] == sid), 0)
    profile.industry_level, profile.adv_industry_level = lv(INDUSTRY), lv(ADV_INDUSTRY)
    con.execute("DELETE FROM character_skills")
    con.executemany("INSERT INTO character_skills(skill_id,level,sp) VALUES(?,?,?)",
                    [(s["skill_id"], s["trained_skill_level"], s.get("skillpoints_in_skill", 0)) for s in skills])
    _sync_attributes_and_queue(con, esi, cid)
    profile.mfg_slots_total = 1 + lv(MASS_PRODUCTION) + lv(ADV_MASS_PRODUCTION)
    jobs = esi.get(f"/characters/{cid}/industry/jobs/")[0]
    profile.mfg_slots_used = sum(1 for j in jobs if j["activity_id"] == 1
                                 and j["status"] in ("active", "paused", "ready"))
    con.execute("DELETE FROM lp_balance")
    con.executemany("INSERT INTO lp_balance VALUES(?,?)",
                    [(x["corporation_id"], x["loyalty_points"])
                     for x in esi.get(f"/characters/{cid}/loyalty/points/")[0]])
    con.execute("DELETE FROM standings")
    con.executemany("INSERT OR REPLACE INTO standings VALUES(?,?)",
                    [(x["from_id"], x["standing"]) for x in esi.get(f"/characters/{cid}/standings/")[0]])
    con.execute("DELETE FROM my_blueprints")
    bps = esi.paged(f"/characters/{cid}/blueprints/")
    con.executemany("INSERT INTO my_blueprints VALUES(?,?,?,?)",
                    [(b["type_id"], b["material_efficiency"], b["time_efficiency"], b["runs"])
                     for b in bps])

    con.execute("DELETE FROM inventory")
    con.execute("DELETE FROM my_ships")
    known = {r[0]: r[1] for r in con.execute("SELECT station_id,system_id FROM stations")}
    known.update({r[0]: r[1] for r in con.execute("SELECT structure_id,system_id FROM structures WHERE system_id>0")})
    skipped = kept = ships = lookups = 0
    cur_ship = ship.get("ship_item_id")
    for a in esi.paged(f"/characters/{cid}/assets/"):
        lid, lt = a["location_id"], a.get("location_type")
        if lid not in known and lookups < 200 and (lt == "station" or (lt == "other" and lid >= 10**12)):
            lookups += 1                       # station/structure not in our data: ask ESI once
            try:
                if lt == "station":
                    info = esi.get(f"/universe/stations/{lid}/")[0]
                    con.execute("INSERT OR REPLACE INTO stations(station_id,system_id,name,corporation_id) "
                                "VALUES(?,?,?,?)", (lid, info["system_id"], info.get("name", ""), info.get("owner")))
                    known[lid] = info["system_id"]
                else:
                    info = esi.get(f"/universe/structures/{lid}/")[0]
                    con.execute("INSERT OR REPLACE INTO structures(structure_id,name,system_id,owner_id,access,info_at) "
                                "VALUES(?,?,?,?,1,strftime('%s','now'))",
                                (lid, info.get("name", ""), info["solar_system_id"], info.get("owner_id")))
                    known[lid] = info["solar_system_id"]
            except Exception:
                known[lid] = None
        sid = known.get(lid) if lt in ("station", "other") else None
        if sid is None or (cur_ship is not None and a.get("item_id") == cur_ship):
            skipped += 1                       # in a container/ship, unknown structure, or the ship you fly
            continue
        if a.get("is_singleton"):
            if _is_ship(con, esi, a["type_id"]):
                con.execute("INSERT OR REPLACE INTO my_ships VALUES(?,?,?,?)", (a.get("item_id", 0), a["type_id"], sid, lid))
                _fill_capacity(con, esi, a["type_id"])
                ships += 1
            else:
                skipped += 1                   # assembled non-ship (container, rigged module...)
            continue
        con.execute("INSERT INTO inventory VALUES(?,?,?) ON CONFLICT(type_id,system_id) "
                    "DO UPDATE SET quantity=quantity+excluded.quantity", (a["type_id"], sid, a["quantity"]))
        kept += 1
    con.commit()
    return {"system": profile.current_system, "ship": profile.ship_name,
            "cargo_m3": profile.cargo_m3, "wallet": wallet, "accounting": lvl,
            "blueprints": len(bps), "lp_corps": con.execute("SELECT COUNT(*) FROM lp_balance").fetchone()[0], "mfg_slots": f"{profile.mfg_slots_used}/{profile.mfg_slots_total}", "assets_kept": kept, "ships_parked": ships, "assets_skipped": skipped,
            "system_known": bool(row)}
