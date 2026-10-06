"""`compare --to Jita`: the same stock, four ways to turn it into ISK, judged by ISK per ACTIVE minute and by the extra
ISK each extra minute buys over just selling here. Listing is cheap in your time but slow in cash; a trip is the reverse."""
from .along import _bids_at, attach_history
from .journey import TIME_VALUE_ISK_HR, plan_journey
from .orders import load_books, sell_into_bids
from .skills import order_slots

SHARE = 0.3          # you capture about this share of a market's daily volume when listing (competitors, price moves)
FAST_DAYS = 7        # "sells fast": expected to clear within this many days
LIST_MIN = 2.0       # active minutes to create one sell order
INSTANT_MIN = 2.0    # dock and open the market
STACK_MIN = 0.7      # per stack sold instantly


def _days(d):
    v = d.get("vol_day")
    return d["qty"] / (v * SHARE) if v else None


def _stacks(con, g, p, min_value=100_000.0):
    """Every stack in the current system's hangar: instant value here, listed value, and the listing advice."""
    cur = g.id_of(p.current_system)
    sells, buys = load_books(con, {cur})
    dock = _bids_at(con, p.current_location_id) if p.current_location_id else None
    name = {r[0]: r[1] for r in con.execute("SELECT type_id,name FROM types")}
    out = []
    for r in con.execute("SELECT type_id,quantity FROM inventory WHERE system_id=?", (cur,)).fetchall():
        tid, qty = r["type_id"], r["quantity"]
        bids = dock.get(tid, []) if dock is not None else buys.get(tid, {}).get(cur, [])
        sold, net = sell_into_bids(bids, qty, p.sales_tax)
        asks = sells.get(tid, {}).get(cur, [])
        listing = qty * asks[0][0] if asks else 0.0
        list_net = listing * (1 - p.broker_fee - p.sales_tax)
        if max(net, list_net) < min_value:
            continue
        out.append({"tid": tid, "name": name.get(tid, tid), "qty": qty, "sold": sold, "net": net, "list_net": list_net,
                    "advice": "LIST" if list_net > net * 1.15 and list_net > 0 else "SELL NOW"})
    slots = order_slots(con)
    lst = sorted([d for d in out if d["advice"] == "LIST"], key=lambda d: -(d["list_net"] - d["net"]))
    if slots is not None:
        for d in lst[slots:]:
            d["advice"] = "SELL NOW"
    return sorted(out, key=lambda d: -max(d["net"], d["list_net"]))


def compare(con, g, p, esi, dest, detour=2, rate=TIME_VALUE_ISK_HR):
    cur = g.id_of(p.current_system)
    here = _stacks(con, g, p)
    res = {"sell_here": here}
    if esi is not None:
        attach_history(esi, res, g.region[cur], cap=25)
    for d in here:
        d["days"] = _days(d)
    listers = [d for d in here if d["advice"] == "LIST"]
    fast = [d for d in listers if d["days"] is not None and d["days"] <= FAST_DAYS]
    S = []

    def instant(stacks):
        return sum(d["net"] for d in stacks), (INSTANT_MIN + STACK_MIN * len(stacks)) if stacks else 0.0

    # A: sell everything instantly here
    t, m = instant(here)
    S.append({"name": "A  Sell it all now, here", "total": t, "min": m, "days": 0.0, "what": f"{len(here)} stacks instantly"})
    # B: list the stacks that pay >15% more listed, instant for the rest
    rest = [d for d in here if d not in listers]
    t = sum(d["list_net"] for d in listers) + instant(rest)[0]
    m = LIST_MIN * len(listers) + instant(rest)[1]
    dd = [d["days"] for d in listers]
    S.append({"name": "B  List here, instant-sell the rest", "total": t, "min": m,
              "days": (max(dd) if dd and None not in dd else (None if dd else 0.0)),
              "what": f"{len(listers)} listed, {len(rest)} instant"})
    # C: journey carrying everything useful, then instant-sell here what it leaves behind
    j = plan_journey(con, g, p, dest, detour, rate)
    left = [d for d in here if (d["tid"], cur) not in j["taken"]]
    t = j["total"] + instant(left)[0]
    m = j["hours"] * 60 + instant(left)[1]
    S.append({"name": f"C  Trip to {dest} with everything", "total": t, "min": m, "days": 0.0,
              "what": f"{j['jumps']} jumps + {j['extra_jumps']} side, {len(j['taken'])} stacks moved/sold"})
    # D: list the fast sellers here, trip with the rest
    skip = {(d["tid"], cur) for d in fast}
    j2 = plan_journey(con, g, p, dest, detour, rate, skip=skip)
    left2 = [d for d in here if d not in fast and (d["tid"], cur) not in j2["taken"]]
    t = sum(d["list_net"] for d in fast) + j2["total"] + instant(left2)[0]
    m = LIST_MIN * len(fast) + j2["hours"] * 60 + instant(left2)[1]
    S.append({"name": f"D  List fast sellers here + trip with the rest", "total": t, "min": m,
              "days": max([d["days"] for d in fast]) if fast else 0.0,
              "what": f"{len(fast)} listed (sell within {FAST_DAYS} days), trip for the rest"})
    base = S[0]
    for s in S:
        s["isk_min"] = s["total"] / s["min"] if s["min"] else 0.0
        extra_m = s["min"] - base["min"]
        s["marginal"] = (s["total"] - base["total"]) / extra_m if extra_m > 0.5 else None
    ok = [s for s in S[1:] if s["marginal"] is not None and s["marginal"] >= rate / 60.0 and s["total"] > base["total"]]
    best = max(ok, key=lambda s: s["total"]) if ok else base
    return {"rows": S, "best": best, "here": here, "fast": fast, "journey": j2 if best is S[3] else j, "rate": rate,
            "dest": dest}


def format_compare(r):
    L = [f"{'':<50} {'total ISK':>14} {'active min':>10} {'ISK/min':>10} {'extra ISK per extra min':>24}  cash arrives"]
    for s in r["rows"]:
        d = s["days"]
        when = "now" if d == 0 else (f"~{d:,.0f} days" if d is not None else "unknown / slow")
        marg = f"{s['marginal']:>24,.0f}" if s["marginal"] is not None else f"{'-':>24}"
        L.append(f"{s['name']:<50} {s['total']:>14,.0f} {s['min']:>10,.0f} {s['isk_min']:>10,.0f} {marg}  {when}")
        L.append(f"     {s['what']}")
    L += ["", f"Your time is valued at {r['rate'] / 60:,.0f} ISK/min ({r['rate']:,.0f} ISK/hr): an option only beats A when its "
              f"'extra ISK per extra min' is above that.", f"BEST: {r['best']['name']}  -> {r['best']['total']:,.0f} ISK for {r['best']['min']:,.0f} active min"]
    if r["fast"]:
        L += ["", f"Sell fast here (expected within {FAST_DAYS} days, assuming you get ~{int(SHARE * 100)}% of market volume):"]
        L += [f"   {d['qty']:>9,} x {d['name']:<32} listed ~{d['list_net']:>13,.0f}  (instant {d['net']:>12,.0f})  ~{d['days']:,.1f} days"
              for d in r["fast"][:10]]
    slow = [d for d in r["here"] if d["advice"] == "LIST" and d not in r["fast"]]
    if slow:
        L += ["", "Listed pays more but sells slowly or unknown (history missing):"]
        L += [f"   {d['qty']:>9,} x {d['name']:<32} listed ~{d['list_net']:>13,.0f}  " +
              (f"~{d['days']:,.0f} days" if d.get("days") else "no volume data") for d in slow[:10]]
    return "\n".join(L)
