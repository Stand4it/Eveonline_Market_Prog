"""`day --hours N`: chain the best tasks over N hours and show ISK, ISK/jump and ISK/hr for each step and overall.
After each step you are where it ended and your wallet has grown (so bigger trades open up). A task that was used is not
reused (its market depth is spent). Greedy by ISK/hr; all risk, tax, time and skill/slot checks come from the normal planner."""
import dataclasses

from .planner import plan
from .sellplan import sell_plan


def _keys(o):
    """What this task uses up: the buy side and the sell side of a trade are separate market depths."""
    d = o.detail
    if o.kind == "liquidate" and "from_sys" in d:
        return {("stock", d["type_id"], d["from_sys"])}               # one stack of stock is sold once, whatever ship/route
    if o.kind == "trade" and "type_id" in d:
        return {("buy", d["type_id"], d.get("from_sys")), ("sell", d["type_id"], d.get("to_sys"))}
    return {(o.kind, o.description)}


STACK_MIN = 0.7        # minutes per stack to sell instantly in the market window
LIST_MIN = 2.0         # minutes to create one sell order


def stock_steps(con, g, p):
    """The stock in your current hangar, first: sell the liquid stacks now (cash), then create the best listings
    (income that arrives over the coming days, so it does NOT raise your wallet now)."""
    res = sell_plan(con, g, dataclasses.replace(p, consider_ship_swaps=False), min_value=100_000.0)
    rows = res["rows"]
    now = [x for x in rows if x["best_label"].startswith("SELL")]
    lst = sorted([x for x in rows if x["best_label"].startswith("LIST")], key=lambda x: -x["list_gain"])
    out, used = [], {("stock", x["tid"], x["sys"]) for x in rows}
    if now:
        out.append({"kind": "sell-now", "what": f"Sell {len(now)} stacks now in {p.current_system}: " +
                    ", ".join(x["name"] for x in now[:4]) + ("..." if len(now) > 4 else ""),
                    "net": sum(x["now"] for x in now), "hours": (2 + STACK_MIN * len(now)) / 60, "jumps": 0, "pending": False})
    for x in lst:
        out.append({"kind": "list", "what": f"List {x['qty']:,} x {x['name']} (about {x['best_net']:,.0f} after fees; sells over days)",
                    "net": x["list_gain"], "hours": LIST_MIN / 60, "jumps": 0, "pending": True})
    return out, used


def build_day(con, g, p, hours=8.0, cash=0.0, max_steps=30, include_stock=True):
    cur = p.current_system
    wallet = p.wallet_isk + cash
    elapsed, total, jumps_total, used, steps = 0.0, 0.0, 0, set(), []
    pending = 0.0
    if include_stock:
        sts, used = stock_steps(con, g, p)
        for s in sts:
            if elapsed + s["hours"] > hours:
                break
            steps.append({"start_h": elapsed, "kind": s["kind"], "what": s["what"], "net": s["net"], "hours": s["hours"],
                          "jumps": 0, "per_jump": 0.0, "per_hr": s["net"] / s["hours"], "from": cur, "to": cur,
                          "wallet": wallet, "pending": s["pending"]})
            elapsed += s["hours"]
            if s["pending"]:
                pending += s["net"]
            else:
                total += s["net"]
                wallet += s["net"]
            steps[-1]["cum"] = total
    for _ in range(max_steps):
        pi = dataclasses.replace(p, current_system=cur, wallet_isk=wallet, consider_ship_swaps=False)   # ship state is not tracked
        left = hours - elapsed
        opps = [o for o in plan(con, pi, 60, False) if not (_keys(o) & used) and o.hours <= left and o.net_isk > 0]
        if not opps:
            break
        o = opps[0]
        steps.append({"start_h": elapsed, "kind": o.kind, "what": o.description, "net": o.net_isk, "hours": o.hours,
                      "jumps": o.jumps, "per_jump": o.isk_per_jump, "per_hr": o.isk_per_hour, "from": cur,
                      "wallet": wallet, "pending": False})
        used |= _keys(o)
        elapsed += o.hours
        total += o.net_isk
        jumps_total += o.jumps
        wallet += o.net_isk
        if o.waypoints:
            cur = g.name[o.waypoints[-1]]
        steps[-1]["to"] = cur
        steps[-1]["cum"] = total
    return {"pending": pending, "steps": steps, "hours": elapsed, "total": total, "jumps": jumps_total, "budget": hours,
            "per_hr": total / elapsed if elapsed else 0.0, "per_jump": total / jumps_total if jumps_total else 0.0}


def _hm(h):
    return f"{int(h)}:{int(round((h - int(h)) * 60)):02d}"


def format_day(res):
    if not res["steps"]:
        return "No task fits in that time. Refresh data (scan --live) or try more hours."
    L = [f"{'at':>5} {'kind':<9} {'net ISK':>13} {'min':>4} {'jumps':>5} {'ISK/jump':>10} {'ISK/hr':>12} {'total so far':>14}  what"]
    for s in res["steps"]:
        later = " later" if s.get("pending") else ""
        L.append(f"{_hm(s['start_h']):>5} {s['kind']:<9} {s['net']:>13,.0f} {s['hours'] * 60:>4.0f} {s['jumps']:>5} "
                 f"{s['per_jump']:>10,.0f} {s['per_hr']:>12,.0f} {s['cum']:>14,.0f}  {s['what'][:70]}{later}")
    if res.get("pending"):
        L += ["", f"PLUS about {res['pending']:,.0f} ISK extra from the listings above, arriving over the next days (not in the totals)."]
    L += ["", f"Over {_hm(res['hours'])} of {_hm(res['budget'])} available: {res['total']:,.0f} ISK cash  =  {res['per_hr']:,.0f} ISK/hr  "
              f"=  {res['per_jump']:,.0f} ISK/jump over {res['jumps']} jumps.",
          "(Estimates: each step is the best task from where the last one ended; prices move, so re-run `scan --live` and "
          "`check` before spending.)"]
    return "\n".join(L)
