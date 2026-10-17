"""Agent missions ON THE WAY of a haul you are flying anyway: accept it at the agent's station before you leave (2 minutes), fly on, do the objective when you
pass through its system, then carry on. Only missions that need no purchase and no known fight, whose objective system lies on the safe route to the haul's destination."""
from .agentchain import _load, stage_text


def _offers():
    import json
    import os
    f = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent_offers.json")
    try:
        return json.load(open(f, encoding="utf-8")).get("offers", [])
    except (OSError, ValueError):
        return []


def _usable(o):
    return o.get("available") and o.get("agent_system") and o.get("to_system") and not o.get("cost") and not o.get("needs")


def step(con, g, p):
    """-> (text, note) for the on-the-way mission step to do NOW, or None."""
    try:
        from .haulchain import load
        st = load(con)
        dest = st["dest"] if st else None
    except Exception:                                                   # noqa: BLE001
        dest = None
    if not dest or dest == p.current_system:
        return None
    try:
        path = [g.name[s] for s in g.route(g.id_of(p.current_system), g.id_of(dest), 60, p.avoid_yellow).path]
    except Exception:                                                   # noqa: BLE001
        return None
    chain = _load(con) or {}
    for o in _offers():
        if not _usable(o):
            continue
        agent = o["agent"].split(" (")[0]
        here_done = chain.get("agent") == agent and chain.get("stage") == "go"
        if here_done and p.current_system == o["to_system"]:
            return stage_text(con, g, p, o), f"{agent}'s objective is in this system, on your way to {dest}"
        if (not here_done and p.current_system == o["agent_system"] and o["to_system"] in path[1:]
                and not (chain.get("agent") == agent and chain.get("stage") == "do")):
            return stage_text(con, g, p, o), f"its objective ({o['to_system']}) is on the route to {dest}: a few minutes of extra ISK as you go"
    return None
