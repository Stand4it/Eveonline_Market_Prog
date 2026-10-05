"""`bpbuy`: which blueprint is worth BUYING to turn the materials you already own into something worth more than selling them?
For every manufacturing blueprint whose materials include stock in your current hangar: run the batch with your own
materials (valued at what they'd sell for NOW), buy any shortfall at the cheapest ask here, sell the product, subtract fees,
then subtract the blueprint's market price. net > 0 => buying the blueprint and building beats selling the materials once.
Assumes a blueprint original at ME0/TE0 (conservative) and that you have the skills (checked if skills were synced)."""
from .manufacturing import buy_cost, build_seconds, material_qty
from .orders import load_books, sell_into_bids
from .skills import blueprint_missing, explain, have


RUN_STEPS = (1, 5, 10, 25, 50, 100, 250, 500, 1000)


def bp_buy_candidates(con, g, p, top=6):
    cur = g.id_of(p.current_system)
    reach = g.reach(cur, p.max_jumps, p.avoid_yellow)
    sells, buys = load_books(con, reach)
    name = {r[0]: r[1] for r in con.execute("SELECT type_id,name FROM types")}
    adj = {r[0]: r[1] for r in con.execute("SELECT type_id,adjusted_price FROM prices")}
    inv = {r[0]: r[1] for r in con.execute("SELECT type_id,quantity FROM inventory WHERE system_id=?", (cur,))}
    if not inv:
        return [], 0
    skills = have(con)
    ids = ",".join(str(int(t)) for t in inv) or "0"
    cand_bps = [r[0] for r in con.execute(f"SELECT DISTINCT blueprint_id FROM bp_materials WHERE material_id IN ({ids})")]
    out, scanned = [], 0
    for bp in cand_bps:
        prod = con.execute("SELECT product_id,quantity,base_time FROM bp_products WHERE blueprint_id=?", (bp,)).fetchone()
        if not prod or prod["product_id"] not in buys:
            continue
        mats = con.execute("SELECT material_id,quantity FROM bp_materials WHERE blueprint_id=?", (bp,)).fetchall()
        lacking = blueprint_missing(con, bp, skills) if skills else []
        scanned += 1
        asks = [a[0][0] for s, a in sells.get(bp, {}).items()]
        bpo = min(asks) if asks else None
        best_row = None
        for runs in RUN_STEPS:                              # a blueprint original can be run many times: try big batches
            need = {m["material_id"]: material_qty(m["quantity"], runs, 0) for m in mats}
            own_value, short_cost, ok, used = 0.0, 0.0, True, []
            for t, q in need.items():
                use = min(q, inv.get(t, 0))
                if use:
                    sold, net = sell_into_bids(buys.get(t, {}).get(cur, []), use, p.sales_tax)
                    own_value += net
                    used.append((name.get(t, t), use))
                if q > use:
                    c = buy_cost(sells.get(t, {}).get(cur, []), q - use)
                    if c is None:
                        ok = False
                        break
                    short_cost += c
            if not ok or not used or own_value < 0.25 * (own_value + short_cost):
                continue
            units = prod["quantity"] * runs
            best = None
            for s2, bids in buys[prod["product_id"]].items():
                sold, net = sell_into_bids(bids, units, p.sales_tax)
                if sold == units and (best is None or net > best[0]):
                    best = (net, s2)
            if not best:
                continue
            fee = sum(m["quantity"] * runs * adj.get(m["material_id"], 0) for m in mats) * p.job_fee_rate
            gain = best[0] - fee - own_value - short_cost
            row = {"blueprint": name.get(bp, bp), "product": name.get(prod["product_id"], prod["product_id"]),
                   "runs": runs, "gain": gain, "bpo_price": bpo, "net": None if bpo is None else gain - bpo,
                   "revenue": best[0], "sell_instead": own_value, "buy_extra": short_cost,
                   "job_hours": build_seconds(prod["base_time"], runs, 0, p) / 3600, "sell_at": g.name[best[1]],
                   "uses": used, "skills_missing": explain(con, lacking) if lacking else ""}
            score = row["net"] if row["net"] is not None else row["gain"] - 1e12
            if best_row is None or score > best_row[0]:
                best_row = (score, row)
        if best_row:
            out.append(best_row[1])
    out = [d for d in out if d["bpo_price"] is not None or d["gain"] > 0]
    out.sort(key=lambda d: -(d["net"] if d["net"] is not None else d["gain"] - 1e12))
    return out[:top], scanned


def format_bpbuy(res, scanned):
    if not res:
        return (f"Checked {scanned} blueprints that use materials you own here: none beats simply selling them.\n"
                "=> SELL. (Blueprints with no seller in range can't be priced; widen --max-jumps or look in the game.)")
    L = [f"Checked {scanned} blueprints that use materials you own here. Best first:"]
    for d in res:
        if d["bpo_price"] is None:
            L.append(f"\nCANNOT PRICE: {d['blueprint']} (no seller in range)  - batch would gain {d['gain']:,.0f}")
            continue
        verdict = "BUY the blueprint and build" if d["net"] > 0 else "NO - not worth buying"
        L.append(f"\n{verdict}: {d['blueprint']}   net after blueprint: {d['net']:,.0f} ISK")
        L.append(f"   blueprint costs {d['bpo_price']:,.0f}; {d['runs']} runs of {d['product']} sell for {d['revenue']:,.0f} at "
                 f"{d['sell_at']}; job {d['job_hours']:.1f} h on one slot (split across free slots to finish sooner)")
        L.append(f"   building gains {d['gain']:,.0f} over selling your materials ({d['sell_instead']:,.0f}); "
                 f"extra materials to buy {d['buy_extra']:,.0f}")
        L.append("   uses your: " + ", ".join(f"{q:,} x {n}" for n, q in d["uses"][:5]))
        if d["skills_missing"]:
            L.append(f"   YOU LACK SKILLS: {d['skills_missing']}")
    return "\n".join(L)
