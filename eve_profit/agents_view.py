"""`agents`: the agents we know about - career agents and their open offers (agent_offers.json), your timed runs with them,
mission agents near you by level (game data), and your standings."""
import json
import os

from .docs import ROOT


def report(con, g, p):
    L = []
    f = os.path.join(ROOT, "agent_offers.json")
    L.append("CAREER AGENTS (Level 1) and their open offers - from agent_offers.json (update it from screenshots):")
    try:
        offers = json.load(open(f, encoding="utf-8")).get("offers", [])
    except (OSError, ValueError):
        offers = []
    seen = {}
    for o in offers:
        name = o["agent"]
        if name.startswith("BOTH"):
            continue
        cur = seen.setdefault(name, {"open": 0, "text": ""})
        if o.get("available", True):
            cur["open"] += 1
            cur["text"] = o["mission"][:70]
    for name, v in seen.items():
        L.append(f"   {name:<46} " + (f"OPEN: {v['text']}" if v["open"] else "no open offer known (screenshot the agent window)"))
    if not seen:
        L.append("   (none known yet)")
    runs = con.execute("SELECT activity,COUNT(*) n,SUM(isk) isk,SUM(hours) h FROM activity_log WHERE activity LIKE 'Agent L1%' GROUP BY activity ORDER BY MIN(ts)").fetchall()
    L.append("\nYOUR TIMED AGENT RUNS (python -m eve_profit activities shows all):")
    L += [f"   {r['activity']:<58} {r['n']} run(s) {r['isk'] / max(r['h'], 1e-9):>12,.0f} ISK/hr  {r['isk']:>10,.0f} ISK" for r in runs] or ["   none yet"]
    L.append("\nMISSION AGENTS NEAR YOU BY LEVEL (game data; names are not in it), within 8 jumps:")
    cur = g.id_of(p.current_system) if p.current_system in g.name.values() else None
    if cur is not None:
        reach = g.reach(cur, 8, p.avoid_yellow)
        by = {}
        for r in con.execute("SELECT level,system_id FROM agents"):
            if r["system_id"] in reach:
                by.setdefault(r["level"], []).append(reach[r["system_id"]].jumps)
        for lvl in sorted(by):
            js = sorted(by[lvl])
            L.append(f"   Level {lvl}: {len(js)} agents, nearest {js[0]} jump(s)")
        if not by:
            L.append("   none found (is the game data loaded? run `diag`)")
    st = con.execute("SELECT from_id,standing FROM standings ORDER BY standing DESC LIMIT 8").fetchall()
    L.append("\nYOUR STANDINGS (from sync; id = agent/corporation/faction):")
    L += [f"   {r['from_id']:<12} {r['standing']:+.2f}" for r in st] or ["   none (run sync)"]
    L.append("\nNext offers ranked by ISK/hr:  python -m eve_profit next      Checklist:  python scripts/agent_steps.py list")
    return "\n".join(L)
