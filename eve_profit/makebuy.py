"""Make-or-buy: for each blueprint you own, what does ONE build really cost from where you are standing, and what is it worth afterwards?
Cost = materials you must buy (cheapest ask in reach, travel counted) + materials from your hangar (valued at what you could sell them for)
       + the job fee.   Worth = SELL (best buy order in reach, after tax and the trip) or KEEP (what buying it again would cost) - the larger one.
If the product is gear you keep, the plain BUY of the finished item is compared too. Everything is measured from your current system."""
from .along import _material_use, keep_names
from .manufacturing import buy_cost, material_qty
from .orders import load_books, sell_into_bids
from .skills import blueprint_missing, have

PER_JUMP_MIN = 3.0
TIME_VALUE_HR = 600000.0          # what your own hour is worth when choosing where to shop (ISK/hr)
BASE_MIN = 4.0                    # minutes to start a build job once the materials are in the hangar
MAX_JUMPS = 6


def _loc_value(minutes):
    return minutes / 60.0 * TIME_VALUE_HR


def options(con, g, p, runs=1, max_jumps=MAX_JUMPS):
    """Every blueprint you own that can be built from here, best first. -> list of dicts (empty if nothing)."""
    try:
        cur = g.id_of(p.current_system)
    except Exception:                                                   # noqa: BLE001
        return []
    reach = g.reach(cur, max_jumps, p.avoid_yellow)
    sells, buys = load_books(con, reach)
    name = {r[0]: r[1] for r in con.execute("SELECT type_id,name FROM types")}
    adj = {r[0]: r[1] for r in con.execute("SELECT type_id,adjusted_price FROM prices")}
    skills = have(con)
    keep = keep_names(con)
    out = []
    for bp, me, te, bp_runs in [(r[0], r[1], r[2], r[3]) for r in con.execute("SELECT blueprint_id,me,te,runs FROM my_blueprints")]:
        if skills and blueprint_missing(con, bp, skills):
            continue
        prod = con.execute("SELECT product_id,quantity,base_time FROM bp_products WHERE blueprint_id=?", (bp,)).fetchone()
        mats = con.execute("SELECT material_id,quantity FROM bp_materials WHERE blueprint_id=?", (bp,)).fetchall()
        if not prod or not mats:
            continue
        r_ = runs if bp_runs < 0 else min(runs, bp_runs)
        if r_ < 1:
            continue
        pid, units = prod["product_id"], prod["quantity"] * r_
        spend, hangar_val, buy_lines, srcs, ok = 0.0, 0.0, [], {}, True
        for m in mats:
            tid, need = m["material_id"], material_qty(m["quantity"], r_, me)
            have_here = con.execute("SELECT COALESCE(SUM(quantity),0) FROM inventory WHERE type_id=? AND system_id=?", (tid, cur)).fetchone()[0]
            use = min(have_here, need)
            if use:
                hangar_val += sell_into_bids(buys.get(tid, {}).get(cur, []), use, p.sales_tax)[1]     # what the hangar stock could fetch
            rem = need - use
            if rem:
                best = None
                for s, asks in sells.get(tid, {}).items():
                    c = buy_cost(asks, rem)
                    if c is not None:
                        score = c + _loc_value(2 * reach[s].jumps * PER_JUMP_MIN)
                        if best is None or score < best[0]:
                            best = (score, c, s)
                if not best:
                    ok = False
                    break
                spend += best[1]
                srcs[best[2]] = srcs.get(best[2], 0) + 1
                buy_lines.append(f"{rem:,} x {name.get(tid, tid)} at {g.name[best[2]]} (~{best[1]:,.0f})")
        if not ok:
            continue
        eiv = sum(m["quantity"] * r_ * adj.get(m["material_id"], 0) for m in mats)
        fee = eiv * p.job_fee_rate
        shop_min = sum(2 * reach[s].jumps * PER_JUMP_MIN + 1 for s in srcs)
        minutes = BASE_MIN + shop_min
        # what the finished item is worth afterwards
        sale = (0.0, None)
        for s, bids in buys.get(pid, {}).items():
            _, net = sell_into_bids(bids, units, p.sales_tax)
            net -= _loc_value(2 * reach[s].jumps * PER_JUMP_MIN)         # the trip to sell it is not free
            if net > sale[0]:
                sale = (net, s)
        asks_p = [(c, s) for s, a in sells.get(pid, {}).items() for c in [buy_cost(a, units)] if c is not None]
        rebuy = min(asks_p) if asks_p else (None, None)
        is_keep = (name.get(pid, "") or "").lower() in keep or _material_use(con, pid)[1] > 0
        keep_val = rebuy[0] if (is_keep and rebuy[0]) else 0.0
        if keep_val >= sale[0] and keep_val > 0:
            kind, value, where = "KEEP", keep_val, "rebuying it would cost this much"
        elif sale[1] is not None and sale[0] > 0:
            kind, value, where = "SELL", sale[0], f"sell now into buy orders at {g.name[sale[1]]} ({reach[sale[1]].jumps} jumps)"
        else:
            kind, value, where = "NONE", 0.0, "no buyer in reach"
        cost = spend + hangar_val + fee
        far_src = max(srcs, key=lambda s_: reach[s_].jumps) if srcs else None
        trip_to = g.name[far_src] if far_src is not None and reach[far_src].jumps > 0 else None
        vol = {r[0]: r[1] for r in con.execute("SELECT type_id,volume FROM types")}
        m3 = sum(material_qty(m["quantity"], r_, me) * (vol.get(m["material_id"], 0) or 0) for m in mats)
        out.append({"trip_to": trip_to, "m3": m3, "blueprint": bp,"product": name.get(pid, str(pid)), "units": units, "runs": r_, "cash": spend + fee, "cost": cost, "value": value,
                    "kind": kind, "where": where, "net": value - cost, "minutes": minutes, "buy": buy_lines, "hangar_val": hangar_val,
                    "buy_instead": (rebuy[0], g.name[rebuy[1]]) if (is_keep and rebuy[0]) else None})
    out.sort(key=lambda o: (-o["net"], o["minutes"]))
    return out


def describe(o):
    """One short paragraph for next: the make-or-buy verdict for this build."""
    L = [f"Build {o['units']} x {o['product']} (Industry > your blueprint, {o['runs']} run, ~{o['minutes']:.0f} min of your time)"]
    if o["buy"]:
        L.append("   buy first: " + "; ".join(o["buy"]))
    else:
        L.append("   every material is already in your hangar")
    L.append(f"   cost ~{o['cost']:,.0f} ISK ({o['cash']:,.0f} cash + {o['hangar_val']:,.0f} of hangar stock at sell-now value)")
    if o["kind"] != "NONE":
        L.append(f"   then {o['kind']}: worth ~{o['value']:,.0f} ({o['where']}) -> {'+' if o['net'] >= 0 else '-'}{abs(o['net']):,.0f} ISK net")
    else:
        L.append("   no buyer in reach: the build only pays the goal, not the item")
    if o["buy_instead"]:
        b, sysn = o["buy_instead"]
        L.append(f"   BUY instead? the finished item costs ~{b:,.0f} at {sysn}: " + ("build is cheaper" if o["cost"] <= b else "BUYING IS CHEAPER, buy it"))
    return "\n".join(L)
