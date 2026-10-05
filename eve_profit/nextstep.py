"""`next`: ONE short instruction at a time. Priority: (1) cash in the liquid stock here, (2) list the single best
high-gap item, (3) the best trade (verify with `check`). Do the step, run `sync`, run `next` again."""
from .along import plan_along
from .planner import plan

AFTER = "Then run:  python -m eve_profit sync   and   python -m eve_profit next"


def next_action(con, g, p):
    res = plan_along(con, g, p, p.current_system)
    here = res["sell_here"]
    where = p.current_system
    docked = "" if p.current_location_id else f"(undocked? dock at a {where} station first)\n"
    sells = [d for d in here if d["advice"] != "LIST" and d["net"] >= 50_000]
    if sells:
        total = sum(d["net"] for d in sells)
        L = [f"STEP: SELL NOW in {where} - about {total:,.0f} ISK", docked.rstrip()]
        for d in sells[:8]:
            L.append(f"   {d['sold']:>9,} x {d['name']:<34} ~{d['net']:>12,.0f}")
        if len(sells) > 8:
            L.append(f"   ...and {len(sells) - 8} more smaller stacks (all marked SELL NOW in `along`)")
        big = sells[0]
        if big["net"] >= 5_000_000:
            L.append(f"   BIG ONE: before selling {big['name']}, compare other markets:  python -m eve_profit bestprice --item \"{big['name']}\"")
        L.append("   In game: Market > item > Sell > pick the HIGHEST buy order at your station.")
        L.append(AFTER)
        return "\n".join(x for x in L if x != "")
    listers = [d for d in here if d["advice"] == "LIST"]
    if listers:
        d = max(listers, key=lambda d: d["list_net"] - d["net"])
        ask = con.execute("SELECT price FROM orders WHERE type_id=? AND system_id=? AND is_buy=0 ORDER BY price ASC LIMIT 1",
                          (d["tid"], g.id_of(where))).fetchone()
        price = ask[0] if ask else d["listing"] / max(d["qty"], 1)
        slots = res.get("slots")
        L = [f"STEP: LIST 1 item in {where}",
             f"   {d['qty']:,} x {d['name']}",
             f"   price each: {price:,.2f}  (the cheapest sell order right now; match or undercut by the smallest step)",
             f"   you receive about {d['list_net']:,.0f} ISK after fees (instant sale would give {d['net']:,.0f})"]
        if slots is not None:
            L.append(f"   uses 1 of your ~{slots} market order slots")
        L.append("   In game: right-click the item in your hangar > Sell this item > choose 'Create sell order'.")
        L.append(AFTER)
        return "\n".join(L)
    opps = [o for o in plan(con, p, 30, False) if o.kind == "trade"]
    if opps:
        o = opps[0]
        return "\n".join([
            "STEP: TRADE (nothing left to sell here)",
            f"   {o.description}",
            f"   profit about {o.net_isk:,.0f} ISK in {o.hours * 60:.0f} min ({o.isk_per_hour:,.0f} ISK/hr)",
            "   FIRST confirm live prices:   python -m eve_profit check --pick 1",
            "   then route:                  python -m eve_profit go --pick 1 --send",
            AFTER])
    return "No clear action. Refresh data:  python -m eve_profit scan --live   then   python -m eve_profit next"
