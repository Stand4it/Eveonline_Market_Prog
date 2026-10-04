"""Collect every activity, rank by risk-adjusted ISK/hour."""
import time

from .graph import Graph
from .mining import find_mining
from .trade import find_liquidations, find_trades

FINDERS = [find_trades, find_liquidations, find_mining]
# Stage 4+: manufacturing, salvage, missions/combat plug in here.


def plan(con, p, top=15, save=True):
    g = Graph(con)
    opps = []
    for f in FINDERS:
        opps.extend(f(con, g, p))
    opps.sort(key=lambda o: o.isk_per_hour, reverse=True)
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
