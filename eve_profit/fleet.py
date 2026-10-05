"""Your other ships and stock: where they are, how long to get there, and whether swapping
into one beats staying in the ship you are flying.
Per-hull combat/cargo numbers come from profile.json `ships` (the game's API can't compute fits):
  "ships": {"Vexor": {"combat_dps": 300, "ship_ehp": 40000, "ship_tank_dps": 150,
                      "ship_value_isk": 15000000, "cargo_m3": 500}}
Without an entry a parked ship is only used for hauling, with cargo = hull capacity."""
import dataclasses

from .opportunity import Opportunity
from .risk import route_risk


def parked_ships(con):
    """-> list of dict(type_id, name, system_id, capacity), one per owned hull per system."""
    out, seen = [], set()
    for r in con.execute("SELECT m.type_id,m.system_id,t.name,t.capacity FROM my_ships m "
                         "JOIN types t ON t.type_id=m.type_id ORDER BY m.item_id"):
        key = (r["type_id"], r["system_id"])
        if key not in seen:
            seen.add(key)
            out.append({"type_id": r["type_id"], "name": r["name"], "system_id": r["system_id"],
                        "capacity": r["capacity"] or 0.0})
    return out


def variant_profile(p, ship, system_name):
    """The profile you'd have after swapping into `ship` at `system_name`."""
    st = p.ships.get(ship["name"], {})
    return dataclasses.replace(
        p, current_system=system_name, ship_name=ship["name"], ship_type_id=ship["type_id"],
        cargo_m3=st.get("cargo_m3", ship["capacity"]),
        ship_value_isk=st.get("ship_value_isk", p.ship_value_isk),
        combat_dps=st.get("combat_dps", 0.0), ship_ehp=st.get("ship_ehp", 0.0),
        ship_tank_dps=st.get("ship_tank_dps", 0.0), mining_yield_m3_s=st.get("mining_yield_m3_s", 0.0),
        can_salvage=st.get("can_salvage", False))


def swap_opportunities(con, g, p, finders, per_variant=5, max_variants=3):
    """For each parked ship within reach: travel there (in your current ship), swap, then the best
    things that ship can do from there. Time/risk of the trip and the swap are charged."""
    cur = g.id_of(p.current_system)
    reach = g.reach(cur, p.max_jumps * 3, p.avoid_yellow)
    cands = [s for s in parked_ships(con) if s["system_id"] in reach
             and not (s["system_id"] == cur and s["type_id"] == p.ship_type_id)]
    cands.sort(key=lambda s: reach[s["system_id"]].cost)
    out = []
    for ship in cands[:max_variants]:
        trip = reach[ship["system_id"]]
        if ship["capacity"] <= 0 and ship["name"] not in p.ships:
            continue                                   # no hold size known and no stats given
        p2 = variant_profile(p, ship, g.name[ship["system_id"]])
        loss, wait = route_risk(g, trip.path, p.ship_value_isk)
        trip_s = trip.jumps * p.jump_seconds + 2 * p.dock_overhead_s + p.swap_overhead_s + wait
        opps = []
        for f in finders:
            if f.__name__ in ("find_mining", "find_manufacturing") and not p.ships.get(ship["name"]):
                continue                    # slow finders only when you gave this hull real stats
            if f.__name__ == "find_combat" and p2.combat_dps <= 0:
                continue                    # combat needs your numbers; skip the work otherwise
            opps.extend(f(con, g, p2))
        opps = [o for o in opps if o.net_isk > 0]
        opps.sort(key=lambda o: o.net_isk / (o.hours + trip_s / 3600), reverse=True)
        for o in opps[:per_variant]:
            out.append(Opportunity(
                o.kind, f"[swap to {ship['name']} @ {g.name[ship['system_id']]}, "
                f"{trip.jumps} jumps away] {o.description}",
                o.profit_isk, o.risk_cost_isk + loss, o.jumps + trip.jumps, o.hours + trip_s / 3600,
                " > ".join(g.name[s] for s in trip.path) + " => " + o.route,
                dict(o.detail, swap_ship=ship["name"], swap_system=g.name[ship["system_id"]],
                     stops=[(i + len(trip.path) - 1 if i >= 0 else len(trip.path) - 1, loc)
                            for i, loc in o.detail.get("stops", [])]),
                trip.path[1:] + o.waypoints))
    return out


def describe_fleet(con, g, p):
    """Lines for the `fleet` command: ships and stock, with travel time from where you are."""
    cur = g.id_of(p.current_system)
    reach = g.reach(cur, p.max_jumps * 6, p.avoid_yellow)
    lines = [f"Flying: {p.ship_name} @ {p.current_system} ({p.cargo_m3:,.0f} m3)"]
    ships = parked_ships(con)
    lines.append(f"\nParked ships ({len(ships)}):")
    for s in sorted(ships, key=lambda s: reach[s["system_id"]].cost if s["system_id"] in reach else 1e9):
        r = reach.get(s["system_id"])
        trip = (f"{r.jumps} jumps, ~{(r.jumps * p.jump_seconds + p.dock_overhead_s) / 60:.0f} min"
                if r else "no safe route in range")
        st = p.ships.get(s["name"])
        lines.append(f"  {s['name']:<22} @ {g.name[s['system_id']]:<14} {trip:<28} hold {s['capacity']:,.0f} m3"
                     + ("  [stats set]" if st else "  [no combat stats]"))
    stock = con.execute("SELECT i.type_id,i.system_id,i.quantity,t.name FROM inventory i JOIN types t "
                        "ON t.type_id=i.type_id").fetchall()
    by_sys = {}
    for r in stock:
        by_sys.setdefault(r["system_id"], 0)
        by_sys[r["system_id"]] += 1
    lines.append(f"\nStock locations ({len(by_sys)} systems, {len(stock)} item stacks):")
    for sid, n in sorted(by_sys.items(), key=lambda kv: reach[kv[0]].cost if kv[0] in reach else 1e9)[:15]:
        r = reach.get(sid)
        lines.append(f"  {g.name.get(sid, sid):<16} {n:>4} stacks   "
                     + (f"{r.jumps} jumps" if r else "no safe route in range"))
    return "\n".join(lines)
