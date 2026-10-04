from dataclasses import dataclass, field


@dataclass
class Opportunity:
    kind: str                 # trade | liquidate | mine | (later) build, salvage, combat
    description: str
    profit_isk: float         # net of taxes, before risk
    risk_cost_isk: float
    jumps: int
    hours: float
    route: str = ""
    detail: dict = field(default_factory=dict)

    @property
    def net_isk(self) -> float:
        return self.profit_isk - self.risk_cost_isk

    @property
    def isk_per_hour(self) -> float:
        return self.net_isk / self.hours if self.hours > 0 else 0.0

    @property
    def isk_per_jump(self) -> float:
        return self.net_isk / max(self.jumps, 1)
