"""`keep`: should the materials you already own be built into something, or sold?
For each blueprint you own: use materials from your hangar (valued at what you could sell them for NOW, the real
opportunity cost), buy any shortfall at the cheapest ask here, sell the product, subtract job fees.
gain > 0 means building beats selling the materials. Build time runs in the background (slot, not your attention)."""
from .manufacturing import buy_cost, build_seconds, material_qty
from .orders import best_sale_anywhere, load_books, sell_into_bids
from .skills import blueprint_missing, free_slots, have


def keep_vs_sell(con, g, p, top=5):
    cur = g.id_of(p.current_system)
    reach = g.reach(cur, max(p.max_jumps * 2, 4), p.avoid_yellow)     # wide enough to value stock at its real best buyer
    sells, buys = load_books(con, reach)
    name = {r[0]: r[1] for r in con.execute("SELECT type_id,name FROM types")}
    adj = {r[0]: r[1] for r in con.execute("SELECT type_id,adjusted_price FROM prices")}
    inv = {r[0]: r[1] for r in con.execute("SELECT type_id,quantity FROM inventory WHERE system_id=?", (cur,))}
    skills = have(con)
    out = []
    for bp in con.execute("SELECT blueprint_id,me,te,runs FROM my_blueprints").fetchall():
        prod = con.execute("SELECT product_id,quantity,base_time FROM bp_products WHERE blueprint_id=?",
                           (bp["blueprint_id"],)).fetchone()
        mats = con.execute("SELECT material_id,quantity FROM bp_materials WHERE blueprint_id=?",
                           (bp["blueprint_id"],)).fetchall()
        if not prod or not mats or prod["product_id"] not in buys:
            continue
        if skills and blueprint_missing(con, bp["blueprint_id"], skills):
            continue
        max_r = p.max_runs if bp["runs"] < 0 else min(p.max_runs, bp["runs"])
        for runs in range(max_r, 0, -1):
            need = {m["material_id"]: material_qty(m["quantity"], runs, bp["me"]) for m in mats}
            own_used, own_value, short_cost, ok = {}, 0.0, 0.0, True
            for t, q in need.items():
                use = min(q, inv.get(t, 0))
                if use:
                    net, sold, _ = best_sale_anywhere(buys.get(t, {}), use, p.sales_tax)   # value at the best buyer in reach
                    own_used[t] = use
                    own_value += net                      # what selling those units would have paid
                if q > use:
                    c = buy_cost(sells.get(t, {}).get(cur, []), q - use)
                    if c is None:
                        ok = False
                        break
                    short_cost += c
            if not ok or not own_used:
                continue
            if own_value < 0.25 * (own_value + short_cost):
                continue          # mostly bought materials: that is ordinary manufacturing (see `scan`), not "keep vs sell"
            units = prod["quantity"] * runs
            best = None
            for s, bids in buys[prod["product_id"]].items():
                sold, net = sell_into_bids(bids, units, p.sales_tax)
                if sold == units and (best is None or net > best[0]):
                    best = (net, s)
            if not best:
                continue
            eiv = sum(m["quantity"] * runs * adj.get(m["material_id"], 0) for m in mats)
            fee = eiv * p.job_fee_rate
            gain = best[0] - fee - own_value - short_cost
            out.append({"product": name.get(prod["product_id"], prod["product_id"]), "runs": runs, "gain": gain,
                        "revenue": best[0], "sell_instead": own_value, "buy_extra": short_cost, "fee": fee,
                        "sell_at": g.name[best[1]], "job_hours": build_seconds(prod["base_time"], runs, bp["te"], p) / 3600,
                        "uses": [(name.get(t, t), q) for t, q in own_used.items()]})
            break                                         # largest feasible batch per blueprint
    out.sort(key=lambda d: -d["gain"])
    return out[:top], free_slots(p)


def format_keep(res, slots):
    if not res:
        return ("None of your blueprints can build from the materials in this hangar (or no buyers for the product).\n"
                "=> SELL the materials; rebuy later only if a build clearly pays.\n"
                "(Builds that need mostly BOUGHT materials are ordinary manufacturing: see `scan` / the 'build' lines.)")
    L = [f"Manufacturing slots free: {slots}.  (gain = product sale - fees - what your own materials would sell for now)"]
    for d in res:
        verdict = "BUILD beats selling" if d["gain"] > 0 else "SELL the materials (building loses)"
        L.append(f"\n{verdict}: {d['runs']} runs of {d['product']}   gain {d['gain']:,.0f} ISK")
        L.append(f"   sells for {d['revenue']:,.0f} at {d['sell_at']}; job {d['job_hours']:.1f} h in the background; "
                 f"fees {d['fee']:,.0f}; extra materials to buy {d['buy_extra']:,.0f}")
        L.append("   uses your: " + ", ".join(f"{q:,} x {n}" for n, q in d["uses"][:5]))
        L.append(f"   or sell those materials now for {d['sell_instead']:,.0f}")
    return "\n".join(L)
