"""Gate graph + safety-aware routing. Red = never, yellow = soft-avoided."""
import heapq
from dataclasses import dataclass

RED_BELOW = 0.5      # low/null/wormhole: forbidden for routes (hard avoid)
YELLOW_BELOW = 0.65  # 0.5-0.6 high-sec edge: allowed, penalised
YELLOW_PENALTY = 4.0  # a yellow system costs as much as this many jumps
KILL_HOT = 5          # >= this many ship kills in the last hour => avoid if possible
GANK_HOT = 2          # >= this many hauler losses in the last 7 days (zKillboard) => treat as a gank hotspot


@dataclass
class Route:
    path: list          # system ids, start..end
    cost: float

    @property
    def jumps(self) -> int:
        return len(self.path) - 1


class Graph:
    def __init__(self, con):
        self.sec, self.name, self.region, self.adj = {}, {}, {}, {}
        for r in con.execute("SELECT system_id,name,security,region_id FROM systems"):
            self.sec[r[0]], self.name[r[0]], self.region[r[0]] = r[2], r[1], r[3]
            self.adj[r[0]] = []
        for a, b in con.execute("SELECT from_id,to_id FROM gates"):
            if a in self.adj and b in self.adj:
                self.adj[a].append(b)
                self.adj[b].append(a)
        self.kills = {r[0]: (r[1] or 0) for r in
                      con.execute("SELECT system_id,ship_kills FROM system_kills")}
        self.gank = {r[0]: r[1] for r in con.execute("SELECT system_id,COUNT(*) FROM gank_events GROUP BY system_id")}
        self._ids = {n.lower(): i for i, n in self.name.items()}
        self.ban_yellow = False     # away mode: never route through 0.5-0.6 or recently-attacked systems
        self.risk_mult = 1.0        # away mode: autopilot is easier to gank -> scale loss odds

    def id_of(self, name: str) -> int:
        return self._ids[name.lower()]

    def is_red(self, s) -> bool:
        return self.sec[s] < RED_BELOW

    def is_yellow(self, s) -> bool:
        return RED_BELOW <= self.sec[s] < YELLOW_BELOW

    def is_hot(self, s) -> bool:
        return self.kills.get(s, 0) >= KILL_HOT or self.gank.get(s, 0) >= GANK_HOT

    def node_cost(self, s, avoid_yellow=True) -> float:
        c = 1.0
        if avoid_yellow and self.is_yellow(s):
            c += YELLOW_PENALTY
        if self.is_hot(s):
            c += YELLOW_PENALTY * 2
        return c

    def reach(self, src, max_jumps, avoid_yellow=True):
        """Dijkstra from src. Returns {system: Route}. Red systems are never entered
        (unless src itself is red: we must leave from where we are)."""
        best = {src: Route([src], 0.0)}
        heap = [(0.0, src)]
        while heap:
            cost, u = heapq.heappop(heap)
            if cost > best[u].cost:
                continue
            if best[u].jumps >= max_jumps:
                continue
            for v in self.adj[u]:
                if self.is_red(v) or (self.ban_yellow and (self.is_yellow(v) or self.is_hot(v))):
                    continue
                nc = cost + self.node_cost(v, avoid_yellow)
                if v not in best or nc < best[v].cost:
                    best[v] = Route(best[u].path + [v], nc)
                    heapq.heappush(heap, (nc, v))
        # Dijkstra with a jump cap can be slightly suboptimal at the boundary; fine.
        return {s: r for s, r in best.items() if r.jumps <= max_jumps}

    def route(self, a, b, max_jumps=40, avoid_yellow=True):
        return self.reach(a, max_jumps, avoid_yellow).get(b)
