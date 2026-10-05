"""Order-book helpers shared by trade/mining."""
from collections import defaultdict


STRUCT_BID_HAIRCUT = 0.0


def set_structure_haircut(profile):
    """Structure owners add their own sales tax. We model it by shaving structure bids so the
    existing `price * (1 - sales_tax)` math nets (1 - tax - structure_tax)."""
    global STRUCT_BID_HAIRCUT
    STRUCT_BID_HAIRCUT = profile.structure_sales_tax / max(1e-9, 1 - profile.sales_tax)


def load_books(con, systems):
    """-> sells[type][system]=[(price,vol,min)] asc ; buys[...] desc."""
    structs = {r[0] for r in con.execute("SELECT structure_id FROM structures")} if STRUCT_BID_HAIRCUT else set()
    sells = defaultdict(lambda: defaultdict(list))
    buys = defaultdict(lambda: defaultdict(list))
    ids = ",".join(str(int(s)) for s in systems) or "0"
    for r in con.execute(
        f"SELECT type_id,system_id,is_buy,price,volume_remain,min_volume,location_id FROM orders "
        f"WHERE system_id IN ({ids})"):
        price = r["price"]
        if r["is_buy"] and r["location_id"] in structs:
            price *= 1 - STRUCT_BID_HAIRCUT
        (buys if r["is_buy"] else sells)[r["type_id"]][r["system_id"]].append(
            (price, r["volume_remain"], r["min_volume"]))
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


def best_sale_anywhere(buys_for_type, qty, tax):
    """Best (net, units_sold, system) for selling `qty` of one item at ANY system in the given {system: bids} map.
    Used to value stock at what you could really get for it, not just at the one station you stand in."""
    best = (0.0, 0, None)
    for system, bids in buys_for_type.items():
        sold, net = sell_into_bids(bids, qty, tax)
        if net > best[0]:
            best = (net, sold, system)
    return best


def walk_trade(asks, bids, max_units, wallet, tax, trace=None):
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
        if trace is not None:
            trace.append((take, ap, bp))
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
