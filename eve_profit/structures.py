"""Player-structure markets (needs login: esi-markets.structure_markets.v1 and
esi-universe.read_structures.v1, plus docking access to each structure).
Flow: list public market structures -> read each structure's system (403 = no access, remembered)
-> download orders only for accessible structures in range -> orders join the normal books, so
trade/contract/manufacturing/LP logic sees them. Structure owners' extra tax: Profile.structure_sales_tax."""
import time
import urllib.error

INFO_TTL = 7 * 86400
INFO_CAP = 200      # structure lookups per refresh (1 ESI call each)
ORDER_CAP = 20      # structures whose orders are downloaded per refresh


def _try(fn):
    try:
        return fn(), None
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404):
            return None, e.code
        raise


def refresh_structures(con, esi, wanted_systems, extra_ids=(), info_cap=INFO_CAP, order_cap=ORDER_CAP):
    """-> dict(known, new_info, denied, orders_fetched, orders_rows)."""
    now = time.time()
    ids, err = _try(lambda: esi.get("/universe/structures/", filter="market")[0])
    ids = list(dict.fromkeys(list(ids or []) + [int(i) for i in extra_ids]))
    have = {r[0]: (r[1], r[2]) for r in con.execute("SELECT structure_id,access,info_at FROM structures")}
    new = denied = 0
    for sid in ids:
        if new + denied >= info_cap:
            break
        acc, at = have.get(sid, (-1, 0))
        if sid in have and (acc == 1 or now - (at or 0) < INFO_TTL):
            continue                       # known good, or recently found inaccessible
        info, code = _try(lambda: esi.get(f"/universe/structures/{sid}/")[0])
        if info:
            con.execute("INSERT OR REPLACE INTO structures(structure_id,name,system_id,owner_id,access,"
                        "info_at) VALUES(?,?,?,?,1,?)",
                        (sid, info.get("name", ""), info["solar_system_id"], info.get("owner_id"), now))
            new += 1
        else:
            con.execute("INSERT OR REPLACE INTO structures(structure_id,access,info_at) VALUES(?,0,?)",
                        (sid, now))
            denied += 1
    wanted = ",".join(str(int(s)) for s in wanted_systems) or "0"
    targets = con.execute(f"SELECT structure_id,system_id FROM structures WHERE access=1 "
                          f"AND system_id IN ({wanted}) ORDER BY orders_at IS NOT NULL, orders_at "
                          f"LIMIT ?", (order_cap,)).fetchall()
    region = {r[0]: r[1] for r in con.execute("SELECT system_id,region_id FROM systems")}
    fetched = rows_n = 0
    for sid, sysid in targets:
        rows, code = _try(lambda: esi.paged(f"/markets/structures/{sid}/"))
        if rows is None:                   # lost access
            con.execute("UPDATE structures SET access=0,info_at=? WHERE structure_id=?", (now, sid))
            continue
        con.execute("DELETE FROM orders WHERE location_id=?", (sid,))
        con.executemany(
            "INSERT OR REPLACE INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [(o["order_id"], o["type_id"], sid, sysid, region.get(sysid, 0), int(o["is_buy_order"]),
              o["price"], o["volume_remain"], o.get("min_volume", 1), o.get("issued", ""), now)
             for o in rows])
        con.execute("UPDATE structures SET orders_at=? WHERE structure_id=?", (now, sid))
        fetched += 1
        rows_n += len(rows)
    con.commit()
    return {"known": len(ids), "new_info": new, "denied": denied,
            "orders_fetched": fetched, "orders_rows": rows_n}
