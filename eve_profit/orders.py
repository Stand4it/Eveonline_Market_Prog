"""Order-book helpers shared by trade/mining."""
from collections import defaultdict


STRUCT_BID_HAIRCUT = 0.0


def set_structure_haircut(profile):
    """Structure owners add their own sales tax. We model it by shaving structure bids so the
    existing `price * (1 - sales_tax)` math nets (1 - tax - structure_tax)."""
    global STRUCT_BID_HAIRCUT
    STRUCT_BID_HAIRCUT = profile.structure_sales_tax / max(1e-9, 1 - profile.sales_tax)
    _TAX[0] = float(profile.sales_tax)


_TAX = [0.045]                              # your sales tax (set from the profile above); default = base 7.5% with Accounting IV


def _station_uplift(today=None):
    """{station id: bid multiplier} for stations with a reduced sales tax today (station_tax.json): a bid there nets
    price x (1 - tax x factor), so it is raised by (1 - tax x factor) / (1 - tax) for the usual price x (1 - tax) math."""
    import datetime
    import json
    import os
    try:
        d = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "station_tax.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    today, t = today or datetime.date.today().isoformat(), _TAX[0]
    return {int(k): (1 - t * float(v.get("factor", 1))) / max(1e-9, 1 - t) for k, v in d.get("stations", {}).items()
            if v.get("from", "") <= today <= v.get("until", "9999")}


_CACHE = {"key": None, "sys": {}}          # per-system books for this run: `next` asked for them 156 times (274 of 417 s)


def _rev(con):
    """The orders revision: a counter in meta that every writer of the orders table moves (bump(con)), in this process or another."""
    try:
        r = con.execute("SELECT value FROM meta WHERE key='orders_rev'").fetchone()
        return r[0] if r else None
    except Exception:                                                   # noqa: BLE001
        return None


def _cache_key(con):
    """Changes whenever the orders could have changed: every writer of the orders table calls `bump(con)` (esi.py, structures.py), which
    moves meta orders_rev for other processes too. Other writes keep the cache: PRAGMA data_version was used before, but a sync running
    beside `next` commits assets/wallet/meta all the time and every commit threw the books and memo away (next > 5 min, 2026-10-31)."""
    return (id(con), _VERSION[0], "frozen" if _FROZEN[0] else _rev(con), STRUCT_BID_HAIRCUT, _TAX[0])


_VERSION = [0]
_FROZEN = [False]


def freeze():
    """This run plans from the books it loads first: orders other processes write meanwhile (a live scan beside `next` saved region after
    region and every save threw the books and memo away: next took 24 min, 2026-10-31) are seen on the next run. Writes in this process
    (bump, refresh_type) still count."""
    _FROZEN[0] = True


def _move_rev(con):
    try:
        con.execute("INSERT INTO meta(key,value) VALUES('orders_rev','1') "
                    "ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1")
    except Exception:                                                   # noqa: BLE001
        pass


def bump(con=None):
    """Call after writing to the orders table: the cached books are stale (here, and with con, in every other process too)."""
    _VERSION[0] += 1
    if con is not None:
        _move_rev(con)


def refresh_type(con, type_id):
    """One item's orders were just re-downloaded (esi.refresh_item): reload that item in the cached books only, instead of dropping every
    cached book (a `next` refreshed single items and then reloaded all books 33 times, 31 s, 2026-10-28)."""
    current = _CACHE["key"] == _cache_key(con)
    _move_rev(con)                                                      # other processes: these orders changed
    if not current or not _CACHE["sys"]:
        return
    _CACHE["key"] = _MEMO["key"] = _cache_key(con)                      # this process: only this item is reloaded below
    _MEMO["d"] = {}                                                     # results built on the old prices are stale
    tid = int(type_id)
    for s_, b_ in _CACHE["sys"].values():
        s_.pop(tid, None)
        b_.pop(tid, None)
    ids = ",".join(str(int(x)) for x in _CACHE["sys"])
    structs = {r[0] for r in con.execute("SELECT structure_id FROM structures")} if STRUCT_BID_HAIRCUT else set()
    up = _station_uplift()
    for r in con.execute(f"SELECT system_id,is_buy,price,volume_remain,min_volume,location_id FROM orders WHERE type_id=? AND system_id IN ({ids})", (tid,)):
        price = r[2] * (1 - STRUCT_BID_HAIRCUT) if r[1] and r[5] in structs else r[2]
        if r[1] and r[5] in up:
            price *= up[r[5]]
        _CACHE["sys"][r[0]][1 if r[1] else 0].setdefault(tid, []).append((price, r[3], r[4]))
    for s_, b_ in _CACHE["sys"].values():
        if tid in s_:
            s_[tid].sort()
        if tid in b_:
            b_[tid].sort(reverse=True)


_MEMO = {"key": None, "d": {}}


def run_memo(con, name, key, fn):
    """fn() once per run for the same (name, key) while the order books are unchanged (same cache key as load_books). `next` asked for the same
    prep chains, shopping list and ship prices 2-14 times (about 150 s of 308, 2026-10-28). A copy is returned so callers may change it.
    Off under unittest: tests reuse connections and mock the inputs."""
    import copy
    import sys
    if "unittest" in sys.modules:
        return fn()
    k = _cache_key(con)
    if _MEMO["key"] != k:
        _MEMO["key"], _MEMO["d"] = k, {}
    if (name, key) not in _MEMO["d"]:
        _MEMO["d"][(name, key)] = fn()
    return copy.deepcopy(_MEMO["d"][(name, key)])


def _load_systems(con, systems):
    """Read the books of `systems` from the DB -> {system: (sells{type:[...]}, buys{type:[...]})}, sorted."""
    structs = {r[0] for r in con.execute("SELECT structure_id FROM structures")} if STRUCT_BID_HAIRCUT else set()
    up = _station_uplift()
    out = {s: ({}, {}) for s in systems}
    ids = ",".join(str(int(s)) for s in systems) or "0"
    for r in con.execute(
        f"SELECT type_id,system_id,is_buy,price,volume_remain,min_volume,location_id FROM orders "
        f"WHERE system_id IN ({ids})"):
        price = r["price"]
        if r["is_buy"] and r["location_id"] in structs:
            price *= 1 - STRUCT_BID_HAIRCUT
        if r["is_buy"] and r["location_id"] in up:
            price *= up[r["location_id"]]                               # a station with a reduced sales tax
        out[r["system_id"]][1 if r["is_buy"] else 0].setdefault(r["type_id"], []).append(
            (price, r["volume_remain"], r["min_volume"]))
    for s_, b_ in out.values():
        for l in s_.values():
            l.sort()
        for l in b_.values():
            l.sort(reverse=True)
    return out


def load_books(con, systems):
    """-> sells[type][system]=[(price,vol,min)] asc ; buys[...] desc. Cached per system for the run (fresh after any DB write)."""
    key = _cache_key(con)
    if _CACHE["key"] != key:
        _CACHE["key"], _CACHE["sys"] = key, {}
    cache = _CACHE["sys"]
    want = {int(s) for s in systems}
    missing = [s for s in want if s not in cache]
    if missing:
        cache.update(_load_systems(con, missing))
    sells = defaultdict(lambda: defaultdict(list))
    buys = defaultdict(lambda: defaultdict(list))
    for s in want:
        s_, b_ = cache[s]
        for t, l in s_.items():
            sells[t][s] = l                                             # shared with the cache: callers only read the lists (checked 2026-10-21)
        for t, l in b_.items():
            buys[t][s] = l
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
