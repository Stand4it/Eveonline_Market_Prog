"""Public contracts: underpriced item bundles (buy contract, sell contents) and courier jobs.
Public ESI only (no login). Structure-located contracts are skipped: their system is unknown
without auth. Safety: only transparent item-exchange/auction/courier contracts; contents that
can't be valued (no buy orders in range, blueprint copies) count as zero; huge 'too good'
margins are flagged CHECK because look-alike-item scams exist -- verify in-game before accepting."""
import calendar
import time
import urllib.error

from .opportunity import Opportunity
from .orders import load_books, sell_into_bids
from .risk import route_risk

SUSPICIOUS_RATIO = 3.0   # contents worth > 3x price => flag
MAX_ITEM_FETCH = 150     # item lookups per refresh (1 ESI call each)


def _ts(iso):
    try:
        return calendar.timegm(time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ"))
    except (TypeError, ValueError):
        return 0


def _paged_or_empty(esi, path):
    try:
        return esi.paged(path)
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            return []
        raise


def _learn_stations(con, esi, station_sys, rows, cap=100):
    """NPC stations we haven't seen (no SDE import): look them up in ESI once and remember."""
    todo = {c.get("start_location_id") for c in rows} | {c.get("end_location_id") for c in rows}
    n = 0
    for lid in sorted(x for x in todo if x and 60000000 <= x < 64000000 and x not in station_sys):
        if n >= cap:
            break
        info, _ = _try_get(esi, f"/universe/stations/{lid}/")
        n += 1
        if info:
            con.execute("INSERT OR REPLACE INTO stations(station_id,system_id,name,corporation_id) "
                        "VALUES(?,?,?,?)", (lid, info["system_id"], info.get("name", ""), info.get("owner")))
            station_sys[lid] = info["system_id"]


def _try_get(esi, path):
    try:
        return esi.get(path)
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            return None, None
        raise


def refresh_contracts(con, esi, region_ids, wanted_systems, cap=MAX_ITEM_FETCH):
    """Replace public contracts for regions; fetch contents for item contracts that start in
    `wanted_systems` (the systems you can reach). -> (contracts_stored, items_fetched)."""
    now = time.time()
    station_sys = {r[0]: r[1] for r in con.execute("SELECT station_id,system_id FROM stations")}
    station_sys.update({r[0]: r[1] for r in con.execute(
        "SELECT structure_id,system_id FROM structures WHERE system_id>0")})
    stored = 0
    for rid in region_ids:
        rows = _paged_or_empty(esi, f"/contracts/public/{rid}/")
        _learn_stations(con, esi, station_sys, rows)
        keep = {r[0]: r[1] for r in con.execute(
            "SELECT contract_id,items_fetched FROM contracts WHERE region_id=?", (rid,))}
        con.execute("DELETE FROM contracts WHERE region_id=?", (rid,))
        for c in rows:
            if c.get("for_corporation") or _ts(c.get("date_expired")) < now:
                continue
            start = station_sys.get(c.get("start_location_id"))
            end = station_sys.get(c.get("end_location_id"), start)
            if start is None:
                continue
            con.execute("INSERT OR REPLACE INTO contracts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (c["contract_id"], rid, c["type"], c.get("price", 0), c.get("reward", 0),
                         c.get("collateral", 0), c.get("volume", 0), c.get("buyout", 0), start, end,
                         _ts(c.get("date_expired")), c.get("days_to_complete", 0),
                         c.get("title", ""), keep.get(c["contract_id"], 0), now))
            stored += 1
    ids = ",".join(str(int(s)) for s in wanted_systems) or "0"
    todo = con.execute(
        f"SELECT contract_id FROM contracts WHERE items_fetched=0 AND type IN "
        f"('item_exchange','auction') AND start_system_id IN ({ids}) "
        f"ORDER BY price ASC LIMIT ?", (cap,)).fetchall()
    for (cid,) in todo:
        items = _paged_or_empty(esi, f"/contracts/public/items/{cid}/")
        con.execute("DELETE FROM contract_items WHERE contract_id=?", (cid,))
        con.executemany("INSERT INTO contract_items VALUES(?,?,?,?,?)",
                        [(cid, i["type_id"], i["quantity"], int(i.get("is_included", True)),
                          int(i.get("is_blueprint_copy", False) or i.get("raw_quantity") == -2))
                         for i in items])
        con.execute("UPDATE contracts SET items_fetched=1 WHERE contract_id=?", (cid,))
    con.execute("DELETE FROM contract_items WHERE contract_id NOT IN "
                "(SELECT contract_id FROM contracts)")
    con.commit()
    return stored, len(todo)


def find_contracts(con, g, p):
    cur = g.id_of(p.current_system)
    reach_a = g.reach(cur, p.pickup, p.avoid_yellow)
    now = time.time()
    ids = ",".join(str(int(s)) for s in reach_a) or "0"
    cons = con.execute(f"SELECT * FROM contracts WHERE start_system_id IN ({ids}) "
                       f"AND (expires IS NULL OR expires=0 OR expires>?)", (now,)).fetchall()
    if not cons:
        return []
    reach_b = {}
    for c in cons:
        a = c["start_system_id"]
        if a not in reach_b:
            reach_b[a] = g.reach(a, p.max_jumps, p.avoid_yellow)
    systems = set(reach_a)
    for r in reach_b.values():
        systems |= set(r)
    _, buys = load_books(con, systems)
    vol = {r[0]: r[1] for r in con.execute("SELECT type_id,volume FROM types")}
    tname = {r[0]: r[1] for r in con.execute("SELECT type_id,name FROM types")}
    out = []
    for c in cons:
        a = c["start_system_id"]
        r1 = reach_a[a]
        if c["type"] == "courier":
            e = c["end_system_id"]
            r2 = reach_b[a].get(e)
            if (not r2 or c["reward"] <= 0 or c["volume"] > p.cargo_m3
                    or c["collateral"] > p.wallet_isk or a == e):
                continue
            exposed = p.ship_value_isk + c["collateral"]
            l1, w1 = route_risk(g, r1.path, p.ship_value_isk)
            l2, w2 = route_risk(g, r2.path, exposed)
            jumps = r1.jumps + r2.jumps
            secs = jumps * p.jump_seconds + 2 * p.dock_overhead_s + w1 + w2
            out.append(Opportunity(
                "courier", f"Courier {c['volume']:,.0f} m3 {g.name[a]} > {g.name[e]}, "
                f"reward {c['reward']:,.0f}, collateral {c['collateral']:,.0f}, "
                f"{c['days_to_complete']}d [#{c['contract_id']}]",
                c["reward"], l1 + l2, jumps, secs / 3600,
                " > ".join(g.name[s] for s in r1.path) + " | " + " > ".join(g.name[s] for s in r2.path),
                {"contract_id": c["contract_id"], "collateral": c["collateral"]},
                r1.path[1:] + r2.path[1:]))
            continue
        price = c["buyout"] if c["type"] == "auction" else c["price"]
        if price <= 0 or price > p.wallet_isk:
            continue
        items = con.execute("SELECT * FROM contract_items WHERE contract_id=?",
                            (c["contract_id"],)).fetchall()
        if not items or any(not i["is_included"] for i in items):   # unknown or "wants items"
            continue
        if sum(i["quantity"] * vol.get(i["type_id"], 1) for i in items) > p.cargo_m3:
            continue
        best = None
        for b, r2 in reach_b[a].items():
            if g.is_hot(b):
                continue          # never plan to deliver into a system with recent kills
            rev = unvalued = 0
            for i in items:
                if i["is_bpc"]:
                    unvalued += 1
                    continue
                sold, net = sell_into_bids(buys[i["type_id"]].get(b, []), i["quantity"], p.sales_tax)
                rev += net
                unvalued += sold < i["quantity"]
            if best is None or rev - price > best[0]:
                best = (rev - price, b, rev, unvalued)
        if not best or best[0] < p.min_profit_isk or best[0] / price < p.min_margin:
            continue
        profit, b, rev, unvalued = best
        r2 = reach_b[a][b]
        l1, w1 = route_risk(g, r1.path, p.ship_value_isk)
        l2, w2 = route_risk(g, r2.path, p.ship_value_isk + price)
        jumps = r1.jumps + r2.jumps
        secs = jumps * p.jump_seconds + 2 * p.dock_overhead_s + p.trade_overhead_s + w1 + w2
        flag = " CHECK-IN-GAME(too good: verify items)" if rev > SUSPICIOUS_RATIO * price else ""
        top = max(items, key=lambda i: i["quantity"])
        out.append(Opportunity(
            "contract", f"Buy contract #{c['contract_id']} ({len(items)} items, e.g. "
            f"{top['quantity']:,} x {tname.get(top['type_id'], top['type_id'])}) for {price:,.0f} @ "
            f"{g.name[a]}, sell @ {g.name[b]}{flag}",
            profit, l1 + l2, jumps, secs / 3600,
            " > ".join(g.name[s] for s in r1.path) + " | " + " > ".join(g.name[s] for s in r2.path),
            {"contract_id": c["contract_id"], "price": price, "revenue": rev,
             "unvalued_items": unvalued}, r1.path[1:] + r2.path[1:]))
    return out
