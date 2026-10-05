"""`day --hours N`: chain the best tasks over N hours and show ISK, ISK/jump and ISK/hr for each step and overall.
After each step you are where it ended and your wallet has grown (so bigger trades open up). A task that was used is not
reused (its market depth is spent). Greedy by ISK/hr; all risk, tax, time and skill/slot checks come from the normal planner."""
import dataclasses

from .planner import plan


def _key(o):
    d = o.detail
    if o.kind == "trade" and "type_id" in d:
        return ("trade", d["type_id"], d.get("from_sys"))
    return (o.kind, o.description)


def build_day(con, g, p, hours=8.0, cash=0.0, max_steps=30):
    cur = p.current_system
    wallet = p.wallet_isk + cash
    elapsed, total, jumps_total, used, steps = 0.0, 0.0, 0, set(), []
    for _ in range(max_steps):
        pi = dataclasses.replace(p, current_system=cur, wallet_isk=wallet)
        left = hours - elapsed
        opps = [o for o in plan(con, pi, 60, False) if _key(o) not in used and o.hours <= left and o.net_isk > 0]
        if not opps:
            break
        o = opps[0]
        steps.append({"start_h": elapsed, "kind": o.kind, "what": o.description, "net": o.net_isk, "hours": o.hours,
                      "jumps": o.jumps, "per_jump": o.isk_per_jump, "per_hr": o.isk_per_hour, "from": cur,
                      "wallet": wallet})
        used.add(_key(o))
        elapsed += o.hours
        total += o.net_isk
        jumps_total += o.jumps
        wallet += o.net_isk
        if o.waypoints:
            cur = g.name[o.waypoints[-1]]
        steps[-1]["to"] = cur
        steps[-1]["cum"] = total
    return {"steps": steps, "hours": elapsed, "total": total, "jumps": jumps_total, "budget": hours,
            "per_hr": total / elapsed if elapsed else 0.0, "per_jump": total / jumps_total if jumps_total else 0.0}


def _hm(h):
    return f"{int(h)}:{int(round((h - int(h)) * 60)):02d}"


def format_day(res):
    if not res["steps"]:
        return "No task fits in that time. Refresh data (scan --live) or try more hours."
    L = [f"{'at':>5} {'kind':<9} {'net ISK':>13} {'min':>4} {'jumps':>5} {'ISK/jump':>10} {'ISK/hr':>12} {'total so far':>14}  what"]
    for s in res["steps"]:
        L.append(f"{_hm(s['start_h']):>5} {s['kind']:<9} {s['net']:>13,.0f} {s['hours'] * 60:>4.0f} {s['jumps']:>5} "
                 f"{s['per_jump']:>10,.0f} {s['per_hr']:>12,.0f} {s['cum']:>14,.0f}  {s['what'][:70]}")
    L += ["", f"Over {_hm(res['hours'])} of {_hm(res['budget'])} available: {res['total']:,.0f} ISK  =  {res['per_hr']:,.0f} ISK/hr  "
              f"=  {res['per_jump']:,.0f} ISK/jump over {res['jumps']} jumps.",
          "(Estimates: each step is the best task from where the last one ended; prices move, so re-run `scan --live` and "
          "`check` before spending.)"]
    return "\n".join(L)
