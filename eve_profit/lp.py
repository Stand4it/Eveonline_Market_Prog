"""Loyalty-point stores: what is one LP worth in ISK, and which LP you hold is worth redeeming.
Offer value = (sell price of the item, after tax, at the best buy orders in range)
              - ISK cost - cost of required items (cheapest asks in range), per LP spent.
Public ESI offers need no login; your LP balance/standings need sync. Offers whose reward
can't be priced from buy orders (blueprint copies etc.) are valued at 0. Analysis-kit (AK)
offers are skipped."""
import time
import urllib.error

from .manufacturing import buy_cost
from .opportunity import Opportunity
from .orders import load_books, sell_into_bids
from .risk import route_risk

REFETCH_S = 86400
MAX_CORPS_PER_REFRESH = 40


def refresh_offers(con, esi, corp_ids, cap=MAX_CORPS_PER_REFRESH):
    """Fetch LP store offers for corporations not fetched in the last day. -> corps fetched."""
    now, n = time.time(), 0
    for cid in corp_ids:
        if n >= cap:
            break
        r = con.execute("SELECT fetched_at FROM lp_fetched WHERE corporation_id=?", (cid,)).fetchone()
        if r and now - r[0] < REFETCH_S:
            continue
        try:
            offers = esi.get(f"/corporations/{cid}/offers/")[0]
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                offers = []
            else:
                raise
        con.execute("DELETE FROM lp_offers WHERE corporation_id=?", (cid,))
        con.execute("DELETE FROM lp_offer_items WHERE corporation_id=?", (cid,))
        for o in offers:
            con.execute("INSERT OR REPLACE INTO lp_offers VALUES(?,?,?,?,?,?,?)",
                        (cid, o["offer_id"], o["type_id"], o["quantity"], o["lp_cost"],
                         o.get("isk_cost", 0), o.get("ak_cost", 0) or 0))
            con.executemany("INSERT INTO lp_offer_items VALUES(?,?,?,?)",
                            [(cid, o["offer_id"], i["type_id"], i["quantity"])
                             for i in o.get("required_items", [])])
        con.execute("INSERT OR REPLACE INTO lp_fetched VALUES(?,?)", (cid, now))
        n += 1
    con.commit()
    return n


def _price_offer(o, reqs, sells, buys, reach, tax, times=1):
    """Value `times` redemptions. -> dict(profit, revenue, cost, sell_at, req_src) or None."""
    units = o["quantity"] * times
    best = None
    for b in reach:
        sold, net = sell_into_bids(buys.get(o["type_id"], {}).get(b, []), units, tax)
        if sold == units and (best is None or net > best[0]):
            best = (net, b)
    if not best:
        return None
    cost, src = o["isk_cost"] * times, set()
    for t, q in reqs:
        opts = [(c, s) for s, a in sells.get(t, {}).items() if s in reach
                for c in [buy_cost(a, q * times)] if c is not None]
        if not opts:
            return None
        c, s = min(opts)
        cost += c
        src.add(s)
    return {"profit": best[0] - cost, "revenue": best[0], "cost": cost,
            "sell_at": best[1], "src": src}


def _offers(con, corp):
    out = []
    for o in con.execute("SELECT * FROM lp_offers WHERE corporation_id=? AND ak_cost=0 AND lp_cost>0",
                         (corp,)):
        reqs = [(r[0], r[1]) for r in con.execute(
            "SELECT type_id,quantity FROM lp_offer_items WHERE corporation_id=? AND offer_id=?",
            (corp, o["offer_id"]))]
        out.append((o, reqs))
    return out


def corp_isk_per_lp(con, p, reach, sells, buys, corps):
    """Best ISK value of one LP per corporation (one redemption of its best offer)."""
    rates = {}
    for corp in set(corps):
        best = 0.0
        for o, reqs in _offers(con, corp):
            v = _price_offer(o, reqs, sells, buys, reach, p.sales_tax)
            if v and v["profit"] / o["lp_cost"] > best:
                best = v["profit"] / o["lp_cost"]
        rates[corp] = best
    return rates


def find_lp_redemptions(con, g, p):
    """Turn LP you already hold into ISK: best offer per corporation within reach."""
    bal = {r[0]: r[1] for r in con.execute("SELECT corporation_id,points FROM lp_balance WHERE points>0")}
    if not bal:
        return []
    cur = g.id_of(p.current_system)
    reach = g.reach(cur, p.max_jumps, p.avoid_yellow)
    sells, buys = load_books(con, reach)
    vol = {r[0]: r[1] for r in con.execute("SELECT type_id,volume FROM types")}
    tname = {r[0]: r[1] for r in con.execute("SELECT type_id,name FROM types")}
    out = []
    for corp, points in bal.items():
        stns = [r for r in con.execute("SELECT station_id,system_id FROM stations WHERE corporation_id=?",
                                       (corp,)) if r[1] in reach]
        if not stns:
            continue                      # no store of that corp within reach
        s_sys = min((r[1] for r in stns), key=lambda x: reach[x].cost)
        best = None
        for o, reqs in _offers(con, corp):
            n = int(points // o["lp_cost"])
            per_m3 = o["quantity"] * vol.get(o["type_id"], 1) + sum(q * vol.get(t, 1) for t, q in reqs)
            if per_m3 > 0:
                n = min(n, int(p.cargo_m3 // per_m3))
            while n >= 1:
                v = _price_offer(o, reqs, sells, buys, reach, p.sales_tax, n)
                if v and v["cost"] <= p.wallet_isk:
                    break
                n -= 1
            if n < 1 or not v or v["profit"] < p.min_profit_isk:
                continue
            if best is None or v["profit"] > best[2]["profit"]:
                best = (o, n, v)
        if not best:
            continue
        o, n, v = best
        r_s, r_b = reach[s_sys], reach[v["sell_at"]]
        tour = []
        for s in sorted(v["src"]):
            tour += reach[s].path[1:] + reach[s].path[::-1][1:]
        tour += r_s.path[1:]
        if v["sell_at"] != s_sys:
            tour += (g.route(s_sys, v["sell_at"], p.max_jumps * 2, p.avoid_yellow).path[1:]
                     if g.route(s_sys, v["sell_at"], p.max_jumps * 2, p.avoid_yellow) else [])
        jumps = len(tour)
        loss, wait = route_risk(g, [cur] + tour, p.ship_value_isk + v["cost"])
        secs = jumps * p.jump_seconds + (len(v["src"]) + 3) * p.dock_overhead_s + p.trade_overhead_s + wait
        out.append(Opportunity(
            "lp-redeem",
            f"Redeem {n}x {tname.get(o['type_id'], o['type_id'])} (uses {n * o['lp_cost']:,} of {points:,} LP, "
            f"{v['profit'] / (n * o['lp_cost']):,.0f} ISK/LP) at corp {corp} store @ {g.name[s_sys]}, "
            f"sell @ {g.name[v['sell_at']]}",
            v["profit"], loss, jumps, secs / 3600, " > ".join(g.name[s] for s in [cur] + tour),
            {"corporation_id": corp, "offer_id": o["offer_id"], "redemptions": n,
             "isk_per_lp": v["profit"] / (n * o["lp_cost"])}, tour))
    return out
