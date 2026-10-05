"""Pull your character state from ESI and update the profile + inventory."""
ACCOUNTING = 16622
INDUSTRY, ADV_INDUSTRY = 3380, 3388
MASS_PRODUCTION, ADV_MASS_PRODUCTION = 3387, 24625
CAPACITY_ATTR = 38


def _type(esi, tid):
    return esi.type_info(tid)


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
    profile.ship_name = ship.get("ship_name", profile.ship_name)
    profile.ship_type_id = ship["ship_type_id"]
    cap = next((a["value"] for a in _type(esi, ship["ship_type_id"]).get("dogma_attributes", [])
                if a["attribute_id"] == CAPACITY_ATTR), None)
    if cap:
        profile.cargo_m3 = cap
    profile.wallet_isk = wallet
    lvl = next((s["trained_skill_level"] for s in skills if s["skill_id"] == ACCOUNTING), 0)
    profile.accounting_level = lvl
    lv = lambda sid: next((s["trained_skill_level"] for s in skills if s["skill_id"] == sid), 0)
    profile.industry_level, profile.adv_industry_level = lv(INDUSTRY), lv(ADV_INDUSTRY)
    con.execute("DELETE FROM character_skills")
    con.executemany("INSERT INTO character_skills VALUES(?,?)",
                    [(s["skill_id"], s["trained_skill_level"]) for s in skills])
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
    known = {r[0]: r[1] for r in con.execute("SELECT station_id,system_id FROM stations")}
    skipped = kept = 0
    for a in esi.paged(f"/characters/{cid}/assets/"):
        sid = known.get(a["location_id"]) if a.get("location_type") == "station" else None
        if sid is None or a.get("is_singleton"):
            skipped += 1      # structures/containers/assembled ships: not tradeable here
            continue
        con.execute("INSERT INTO inventory VALUES(?,?,?) ON CONFLICT(type_id,system_id) "
                    "DO UPDATE SET quantity=quantity+excluded.quantity",
                    (a["type_id"], sid, a["quantity"]))
        kept += 1
    con.commit()
    return {"system": profile.current_system, "ship": profile.ship_name,
            "cargo_m3": profile.cargo_m3, "wallet": wallet, "accounting": lvl,
            "blueprints": len(bps), "lp_corps": con.execute("SELECT COUNT(*) FROM lp_balance").fetchone()[0], "mfg_slots": f"{profile.mfg_slots_used}/{profile.mfg_slots_total}", "assets_kept": kept, "assets_skipped": skipped,
            "system_known": bool(row)}
