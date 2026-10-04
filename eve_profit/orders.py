"""Order-book helpers shared by trade/mining."""
from collections import defaultdict


def load_books(con, systems):
    """-> sells[type][system]=[(price,vol,min)] asc ; buys[...] desc."""
    sells = defaultdict(lambda: defaultdict(list))
    buys = defaultdict(lambda: defaultdict(list))
    ids = ",".join(str(int(s)) for s in systems) or "0"
    for r in con.execute(
        f"SELECT type_id,system_id,is_buy,price,volume_remain,min_volume FROM orders "
        f"WHERE system_id IN ({ids})"):
        (buys if r["is_buy"] else sells)[r["type_id"]][r["system_id"]].append(
            (r["price"], r["volume_remain"], r["min_volume"]))
    for book in sells.values():
        for l in book.values():
            l.sort()
    for book in buys.values():
        for l in book.values():
            l.sort(reverse=True)
    return sells, buys


def sell_into_bids(bids, units, tax):
    """Instant-sell `units` into buy orders. -> (units_sold, net_isk)."""
    sold, net = 0, 0.0
    for price, vol, minv in bids:
        if sold >= units:
            break
        take = min(vol, units - sold)
        if take < minv:
            continue
        sold += take
        net += take * price * (1 - tax)
    return sold, net


def walk_trade(asks, bids, max_units, wallet, tax):
    """Buy from asks, sell into bids while each marginal unit stays profitable.
    -> (units, cost, net_revenue)."""
    ai = bi = 0
    a_left = asks[0][1] if asks else 0
    b_left = bids[0][1] if bids else 0
    units, cost, rev = 0, 0.0, 0.0
    while ai < len(asks) and bi < len(bids) and units < max_units:
        ap, bp = asks[ai][0], bids[bi][0]
        if bp * (1 - tax) <= ap:
            break
        take = min(a_left, b_left, max_units - units, int((wallet - cost) // ap))
        if take <= 0:
            break
        if take < bids[bi][2]:           # below the buy order's minimum volume
            bi += 1
            b_left = bids[bi][1] if bi < len(bids) else 0
            continue
        units += take
        cost += take * ap
        rev += take * bp * (1 - tax)
        a_left -= take
        b_left -= take
        if a_left <= 0:
            ai += 1
            a_left = asks[ai][1] if ai < len(asks) else 0
        if b_left <= 0:
            bi += 1
            b_left = bids[bi][1] if bi < len(bids) else 0
    return units, cost, rev
