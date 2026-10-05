"""Settings and the player's ship/skill profile."""
import json
import os
import platform
from dataclasses import dataclass, field, asdict

USER_AGENT = "eve-profit-planner/0.1 (contact: dahlmartin4@gmail.com)"


def default_db_path() -> str:
    """E:\\EveProfit\\eve_profit.db on Windows (requested); ./data elsewhere."""
    env = os.environ.get("EVE_PROFIT_DB")
    if env:
        return env
    if platform.system() == "Windows" and os.path.isdir("E:\\"):
        return "E:\\EveProfit\\eve_profit.db"
    return os.path.join("data", "eve_profit.db")


@dataclass
class Profile:
    """What the planner knows about you. Stage 3 fills this from ESI."""
    ship_name: str = "Generic hauler"
    current_system: str = "Home"
    cargo_m3: float = 5000.0          # general cargo
    ore_hold_m3: float = 0.0          # 0 -> mining uses cargo_m3
    ship_value_isk: float = 20_000_000.0
    wallet_isk: float = 50_000_000.0
    max_jumps: int = 2                # search radius from current system
    secs_per_jump: float = 45.0       # align + warp + gate + session change
    autopilot: bool = False           # autopilot is slower and riskier
    dock_overhead_s: float = 60.0
    trade_overhead_s: float = 90.0
    mining_yield_m3_s: float = 0.0    # 0 = cannot mine
    minable_ores: list = field(default_factory=list)
    accounting_level: int = 4         # sales tax reduction
    sales_tax_base: float = 0.045     # verify in-game; Stage 3 reads skills
    industry_level: int = 5           # skill 3380: -4% build time/level
    adv_industry_level: int = 3       # skill 3388: -3% build time/level
    max_runs: int = 10                # runs per batch considered
    job_fee_rate: float = 0.05        # fee on estimated item value (SCC 4% + system index); verify
    assume_all_blueprints: bool = False  # True = rank every buildable item (what to buy a BP for)
    avoid_yellow: bool = True         # soft avoid
    min_profit_isk: float = 100_000.0
    min_margin: float = 0.03

    @property
    def sales_tax(self) -> float:
        return self.sales_tax_base * (1 - 0.11 * self.accounting_level)

    @property
    def jump_seconds(self) -> float:
        return self.secs_per_jump * (1.6 if self.autopilot else 1.0)

    @property
    def mining_hold(self) -> float:
        return self.ore_hold_m3 or self.cargo_m3

    @classmethod
    def load(cls, path: str | None) -> "Profile":
        if path and os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
            known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
            return cls(**known)
        return cls()

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)
