"""Expected-loss model. Numbers are tunable guesses, not CCP data."""
from .graph import Graph

# probability per system transit of losing the ship+cargo while hauling
P_LOSS = {"green": 0.0002, "yellow": 0.002}
HOT_MULT = 5.0
# time cost of waiting out a hot system docked up
HOT_WAIT_S = 600.0


def route_risk(g: Graph, path, exposed_value: float):
    """Return (expected_loss_isk, wait_seconds) for a route."""
    loss = wait = 0.0
    for s in path[1:]:
        p = P_LOSS["yellow" if g.is_yellow(s) else "green"]
        if g.is_hot(s):
            p *= HOT_MULT
            wait += HOT_WAIT_S
        loss += p * exposed_value
    return loss, wait
