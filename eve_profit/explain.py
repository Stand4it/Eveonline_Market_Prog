"""`explain --pick N`: show the order-book steps behind a ranked trade so you can check it in the game."""
from .orders import load_books, walk_trade


def _where(con, g, tid, system, is_buy, label):
    """Top orders in `system` with their station/structure name, region and data age."""
    import time
    out = []
    order = "DESC" if is_buy else "ASC"
    rows = con.execute(f"SELECT price,volume_remain,min_volume,location_id,region_id,fetched_at FROM orders "
                       f"WHERE type_id=? AND system_id=? AND is_buy=? ORDER BY price {order} LIMIT 3",
                       (tid, system, is_buy)).fetchall()
    for r in rows:
        st = con.execute("SELECT name FROM stations WHERE station_id=?", (r["location_id"],)).fetchone()
        sc = con.execute("SELECT name FROM structures WHERE structure_id=?", (r["location_id"],)).fetchone()
        if sc:
            kind = f"PLAYER STRUCTURE '{sc[0] or r['location_id']}' - not shown in the in-game regional market; only visible when docked there"
        elif st:
            kind = f"NPC station {st[0]!r}" if st[0] else f"NPC station id {r['location_id']} (a normal station market)"
        else:
            kind = f"location {r['location_id']}"
        age = (time.time() - r["fetched_at"]) / 60
        out.append(f"   {label} {r['volume_remain']:>7,} @ {r['price']:>12,.2f} (min qty {r['min_volume']}) in {g.name[system]}, "
                   f"region id {r['region_id']}: {kind}; data {age:,.0f} min old")
    return out or [f"   {label} no orders found in {g.name[system]}"]


def explain_trade(con, g, p, opp):
    d = opp.detail
    if opp.kind != "trade" or "from_sys" not in d:
        return "explain currently supports trades (kind 'trade') only."
    a, b, tid = d["from_sys"], d["to_sys"], d["type_id"]
    name = con.execute("SELECT name,volume FROM types WHERE type_id=?", (tid,)).fetchone()
    sells, buys = load_books(con, {a, b})
    asks, bids = sells[tid][a], buys[tid][b]
    trace = []
    cap = int(p.cargo_m3 // name["volume"]) if name["volume"] else 10**9
    units, cost, rev = walk_trade(asks, bids, cap, p.wallet_isk, p.sales_tax, trace)
    L = [f"{name['name']}: buy @ {g.name[a]}, sell @ {g.name[b]}   (hold fits {cap:,} units, wallet {p.wallet_isk:,.0f})",
         "", f"BUY in {g.name[a]} (cheapest sell orders, in the order you would take them):"]
    for price, vol, _ in asks[:8]:
        L.append(f"   {vol:>9,} units @ {price:>14,.2f}")
    L += ["", f"SELL in {g.name[b]} (highest buy orders; structure buyers shown after the owner's tax allowance):"]
    for price, vol, _ in bids[:8]:
        L.append(f"   {vol:>9,} units @ {price:>14,.2f}")
    L += ["", "WHERE those orders are (check these in the game before buying):"]
    L += _where(con, g, tid, a, 0, "BUY ") + _where(con, g, tid, b, 1, "SELL")
    L += ["", "Plan, step by step (buy price -> matching buy order):"]
    for q, ap, bp in trace:
        L.append(f"   {q:>9,} units: buy at {ap:>12,.2f}, sell at {bp:>12,.2f}  (+{q * (bp * (1 - p.sales_tax) - ap):,.0f} ISK)")
    L += ["", f"Total: {units:,} units, pay {cost:,.0f}, receive {rev:,.0f} after {p.sales_tax * 100:.2f}% sales tax, "
              f"profit {rev - cost:,.0f} ({(rev - cost) / cost * 100:.1f}% of cost)" if cost else "Nothing to trade."]
    if cost:
        L.append(f"Wallet left after buying: {p.wallet_isk - cost:,.0f}.  Walk away if the first sell price you see is "
                 f"more than ~{max(1, int(0.01 * cost / max(units, 1)))} ISK/unit above the first line above.")
    return "\n".join(L)
