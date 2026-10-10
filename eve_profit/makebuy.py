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
MAX_RUNS = 10


def _loc_value(minutes):
    return minutes / 60.0 * TIME_VALUE_HR


def options(con, g, p, runs=1, max_jumps=MAX_JUMPS, free=None):
    """Every blueprint you own that can be built from here, best first. -> list of dicts (empty if nothing).
    free = system ids you are travelling through anyway (a trip you already planned): buying there costs no extra travel."""
    free = set(free or ())
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
        top = MAX_RUNS if bp_runs < 0 else min(MAX_RUNS, bp_runs)
        cand = []
        for r_ in range(1, top + 1):
          o_ = _one(con, g, p, reach, sells, buys, name, adj, keep, bp, me, te, bp_runs, prod, mats, r_, free)
          if o_:
              cand.append(o_)
        if cand:
            out.append(max(cand, key=lambda o: (o["net"], -o["runs"])))
    out.sort(key=lambda o: (-o["net"], o["minutes"]))
    return out


def _one(con, g, p, reach, sells, buys, name, adj, keep, bp, me, te, bp_runs, prod, mats, r_, free=frozenset()):
    """One blueprint at one run count -> option dict or None."""
    cur = g.id_of(p.current_system)
    if True:
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
                        score = c + (0.0 if s in free else _loc_value(2 * reach[s].jumps * PER_JUMP_MIN))
                        if best is None or score < best[0]:
                            best = (score, c, s)
                if not best:
                    ok = False
                    break
                spend += best[1]
                srcs[best[2]] = srcs.get(best[2], 0) + 1
                buy_lines.append(f"{rem:>7,} x {str(name.get(tid, tid)):<16} at {g.name[best[2]]:<12} ~{best[1]:>9,.0f} ISK" + ("   (on your route)" if best[2] in free else ""))
        if not ok:
            return None
        eiv = sum(m["quantity"] * r_ * adj.get(m["material_id"], 0) for m in mats)
        fee = eiv * p.job_fee_rate
        shop_min = sum((0.0 if s in free else 2 * reach[s].jumps * PER_JUMP_MIN) + 1 for s in srcs)
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
        paid = [s_ for s_ in srcs if s_ not in free]
        far_src = max(paid, key=lambda s_: reach[s_].jumps) if paid else None
        trip_to = g.name[far_src] if far_src is not None and reach[far_src].jumps > 0 else None
        vol = {r[0]: r[1] for r in con.execute("SELECT type_id,volume FROM types")}
        m3 = sum(material_qty(m["quantity"], r_, me) * (vol.get(m["material_id"], 0) or 0) for m in mats)
        from .manufacturing import build_seconds
        job_min = build_seconds(prod["base_time"], r_, te, p) / 60.0
        return ({"trip_to": trip_to, "m3": m3, "job_min": job_min, "blueprint": bp, "product": name.get(pid, str(pid)), "units": units, "runs": r_, "cash": spend + fee, "cost": cost, "value": value,
                    "kind": kind, "where": where, "net": value - cost, "minutes": minutes, "buy": buy_lines, "hangar_val": hangar_val,
                    "buy_instead": (rebuy[0], g.name[rebuy[1]]) if (is_keep and rebuy[0]) else None})


def describe(o):
    """The make-or-buy verdict for next, one fact per line."""
    L = [f"Build {o['units']} x {o['product']}   ({o['runs']} run{'s' if o['runs'] != 1 else ''} of your blueprint, Industry window)",
         f"   your time   ~{o['minutes']:.0f} min to buy and start it; the job then runs ~{o.get('job_min', 0):.0f} min in the background"]
    if o["buy"]:
        L.append("   BUY FIRST:")
        L += ["      " + b for b in o["buy"]]
    else:
        L.append("   materials   all already in your hangar")
    L.append(f"   cost        ~{o['cost']:,.0f} ISK  ({o['cash']:,.0f} cash + {o['hangar_val']:,.0f} hangar stock at sell-now value)")
    if o["kind"] != "NONE":
        L.append(f"   afterwards  {o['kind']} ~{o['value']:,.0f} ISK ({o['where']}) = {'+' if o['net'] >= 0 else '-'}{abs(o['net']):,.0f} ISK net")
    else:
        L.append("   afterwards  no buyer in reach: only the daily goal pays for this build")
    if o["buy"]:
        eq = o["cash"] / TIME_VALUE_HR * 60.0
        L.append(f"   buy or mine the materials?  buying = {eq:.1f} min of your time at {TIME_VALUE_HR:,.0f} ISK/hr -> "
                 + ("BUY (mining takes longer)" if eq < 15 else "mining may be cheaper: check a mining run"))
    alone = o["net"] * 60.0 / max(o["minutes"], 1.0)
    L.append(f"   alone       {'+' if alone >= 0 else '-'}{abs(alone):,.0f} ISK per active hour" + ("  (its value here is the goal)" if o["kind"] == "NONE" else ""))
    if o["buy_instead"]:
        b, sysn = o["buy_instead"]
        L.append(f"   BUY instead?  the finished item costs ~{b:,.0f} at {sysn}: " + ("build is cheaper" if o["cost"] <= b else "BUYING IS CHEAPER, buy it"))
    return "\n".join(L)
