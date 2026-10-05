"""Manufacturing: buy materials, build, sell product. Build time runs in the background,
so ranking uses YOUR active time (shopping/hauling/overhead); job_hours is reported."""
import math

from .opportunity import Opportunity
from .orders import load_books, sell_into_bids
from .risk import route_risk
from .skills import blueprint_missing, free_slots, have


def material_qty(base, runs, me):
    """EVE rule: max(runs, ceil(base*runs*(1-ME%))), rounded to dodge float noise."""
    return max(runs, math.ceil(round(base * runs * (1 - me / 100), 2)))


def build_seconds(base_time, runs, te, p):
    mult = ((1 - te / 100) * (1 - 0.04 * p.industry_level) * (1 - 0.03 * p.adv_industry_level))
    return base_time * runs * mult


def buy_cost(asks, units):
    """Cost to buy `units` walking the ask book, or None if not enough supply."""
    cost, need = 0.0, units
    for price, vol, _ in asks:
        take = min(vol, need)
        cost += take * price
        need -= take
        if need == 0:
            return cost
    return None


def find_manufacturing(con, g, p):
    if free_slots(p) <= 0:
        return []                     # every manufacturing slot is busy
    skills = have(con)                # empty = not synced -> skill check skipped
    cur = g.id_of(p.current_system)
    reach = g.reach(cur, p.max_jumps, p.avoid_yellow)
    sells, buys = load_books(con, reach)
    vol = {r[0]: r[1] for r in con.execute("SELECT type_id,volume FROM types")}
    name = {r[0]: r[1] for r in con.execute("SELECT type_id,name FROM types")}
    adj = {r[0]: r[1] for r in con.execute("SELECT type_id,adjusted_price FROM prices")}
    if p.assume_all_blueprints:
        bps = [(r[0], 0, 0, -1) for r in con.execute("SELECT blueprint_id FROM bp_products")]
    else:
        bps = [(r[0], r[1], r[2], r[3]) for r in con.execute(
            "SELECT blueprint_id,me,te,runs FROM my_blueprints")]
    out = []
    for bp, me, te, bp_runs in bps:
        if skills and blueprint_missing(con, bp, skills):
            continue                  # you lack a required skill
        prod = con.execute("SELECT product_id,quantity,base_time FROM bp_products "
                           "WHERE blueprint_id=?", (bp,)).fetchone()
        mats = con.execute("SELECT material_id,quantity FROM bp_materials "
                           "WHERE blueprint_id=?", (bp,)).fetchall()
        if not prod or not mats or prod["product_id"] not in buys:
            continue
        max_r = p.max_runs if bp_runs < 0 else min(p.max_runs, bp_runs)   # BPC has limited runs
        for runs in range(max_r, 0, -1):
            need = {m["material_id"]: material_qty(m["quantity"], runs, me) for m in mats}
            if sum(q * vol.get(t, 1) for t, q in need.items()) > p.cargo_m3:
                continue
            units = prod["quantity"] * runs
            plan, cost, ok = {}, 0.0, True
            for t, q in need.items():
                best = None
                for s, asks in sells.get(t, {}).items():
                    c = buy_cost(asks, q)
                    if c is not None and (best is None or c < best[0]):
                        best = (c, s)
                if not best:
                    ok = False
                    break
                cost += best[0]
                plan[t] = best[1]
            if not ok:
                continue
            eiv = sum(m["quantity"] * runs * adj.get(m["material_id"], 0) for m in mats)
            fee = eiv * p.job_fee_rate
            if cost + fee > p.wallet_isk:
                continue
            sold_best = None
            for s, bids in buys[prod["product_id"]].items():
                sold, net = sell_into_bids(bids, units, p.sales_tax)
                if sold == units and (sold_best is None or net > sold_best[0]):
                    sold_best = (net, s)
            if not sold_best:
                continue
            profit = sold_best[0] - cost - fee
            if profit < p.min_profit_isk or profit / (cost + fee) < p.min_margin:
                continue
            srcs = set(plan.values())
            jumps = sum(2 * reach[s].jumps for s in srcs) + 2 * reach[sold_best[1]].jumps
            loss = wait = 0.0
            for s in srcs | {sold_best[1]}:
                l, w = route_risk(g, reach[s].path, p.ship_value_isk + cost)
                loss += 2 * l
                wait += 2 * w
            active = (jumps * p.jump_seconds + (len(srcs) + 2) * p.dock_overhead_s
                      + p.trade_overhead_s + wait)
            job_h = build_seconds(prod["base_time"], runs, te, p) / 3600
            tour = []
            for s in sorted(srcs):      # out-and-back to each source, then the buyer
                tour += reach[s].path[1:] + reach[s].path[::-1][1:]
            tour += reach[sold_best[1]].path[1:]
            out.append(Opportunity(
                "build",
                f"Build {runs}x {name.get(prod['product_id'], bp)} (ME{me}/TE{te}), "
                f"job {job_h:.1f}h, sell @ {g.name[sold_best[1]]}",
                profit, loss, jumps, active / 3600,
                "buy@" + ",".join(sorted(g.name[s] for s in srcs)) + " > sell@" + g.name[sold_best[1]],
                {"blueprint": bp, "runs": runs, "units": units, "cost": cost, "fee": fee,
                 "job_hours": job_h}, waypoints=tour))
            break  # largest feasible batch wins for this blueprint
    return out
