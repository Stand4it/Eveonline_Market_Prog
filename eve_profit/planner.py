"""Collect every activity, rank by risk-adjusted ISK/hour."""
import time

from .graph import Graph
from .combat import find_combat
from .contracts import find_contracts
from .lp import find_lp_redemptions
from .manufacturing import find_manufacturing
from .mining import find_mining
from .skills import free_slots
from .trade import find_liquidations, find_trades

FINDERS = [find_trades, find_liquidations, find_mining, find_manufacturing, find_combat, find_contracts, find_lp_redemptions]
# Stage 6: route automation / alerts.


HAUL_FINDERS = [find_trades, find_liquidations, find_contracts, find_lp_redemptions]


def away_profile(p):
    """Unattended: autopilot timing, long deliveries, short pickups, haul-type tasks only."""
    import dataclasses
    return dataclasses.replace(p, autopilot=True, max_jumps=p.away_max_jumps,
                               pickup_jumps=p.pickup_jumps or 3, avoid_yellow=True,
                               consider_ship_swaps=False)


def plan(con, p, top=15, save=True):
    from .orders import set_structure_haircut
    if p.away_mode:
        p = away_profile(p)
    set_structure_haircut(p)
    g = Graph(con)
    if p.away_mode:
        g.ban_yellow, g.risk_mult = True, 3.0
    opps = []
    import os, time as _t
    timing = os.environ.get("EVE_PROFIT_TIMING")
    for f in (HAUL_FINDERS if p.away_mode else FINDERS):
        t0 = _t.time()
        opps.extend(f(con, g, p))
        if timing:
            print(f"  [timing] {f.__name__}: {_t.time() - t0:.1f}s", flush=True)
    if p.consider_ship_swaps:
        from .fleet import swap_opportunities
        t0 = _t.time()
        opps.extend(swap_opportunities(con, g, p, FINDERS))
        if timing:
            print(f"  [timing] ship swaps: {_t.time() - t0:.1f}s", flush=True)
    opps = [o for o in opps if o.net_isk > 0]     # never recommend a task that loses ISK after risk
    opps.sort(key=lambda o: o.isk_per_hour, reverse=True)
    slots, kept = free_slots(p), []
    for o in opps:                    # each build occupies one manufacturing slot
        if o.kind == "build":
            if slots <= 0:
                continue
            slots -= 1
        kept.append(o)
    opps = kept
    if save:
        now = time.time()
        con.executemany(
            "INSERT INTO opportunities(scanned_at,kind,description,profit_isk,risk_cost_isk,"
            "jumps,hours,isk_per_jump,isk_per_hour,route,detail) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [(now, o.kind, o.description, o.profit_isk, o.risk_cost_isk, o.jumps, o.hours,
              o.isk_per_jump, o.isk_per_hour, o.route, repr(o.detail)) for o in opps[:200]])
        con.commit()
    return opps[:top]


def format_plan(opps) -> str:
    if not opps:
        return "No profitable opportunities found in range."
    lines = [f"{'#':>2} {'kind':<9} {'ISK/hr':>12} {'ISK/jump':>12} {'jumps':>5} "
             f"{'min':>5} {'net ISK':>12}  what"]
    for i, o in enumerate(opps, 1):
        lines.append(f"{i:>2} {o.kind:<9} {o.isk_per_hour:>12,.0f} {o.isk_per_jump:>12,.0f} "
                     f"{o.jumps:>5} {o.hours * 60:>5.0f} {o.net_isk:>12,.0f}  {o.description}")
        lines.append(f"{'':>2} route: {o.route}")
    return "\n".join(lines)
