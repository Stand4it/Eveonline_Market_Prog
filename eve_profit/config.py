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


def guard_db(path):
    """Never silently start a SECOND database: if the folder the tool used last time (e.g. E:\\EveProfit) is not there now (drive unplugged, other letter),
    stop with a clear message instead of creating an empty database in ./data. The last folder is remembered in .last_db."""
    if os.environ.get("EVE_NO_GUARD"):
        return
    if (platform.system() == "Windows" and not os.environ.get("EVE_PROFIT_DB") and not os.environ.get("EVE_PROFIT_ALLOW_DATA")
            and os.path.normpath(path) == os.path.normpath(os.path.join("data", "eve_profit.db")) and not os.path.isdir("E:\\")):
        raise SystemExit("STOP: the E: drive (E:\\EveProfit, where your database lives) is not available, so the tool would fall back to an EMPTY database in the project's data folder. "
                         "Reconnect the E: drive and run again. (To use data\\ on purpose: set the environment variable EVE_PROFIT_ALLOW_DATA=1, or pass --db PATH.)")
    here = os.path.dirname(os.path.abspath(path))
    try:
        last = open(".last_db", encoding="utf-8").read().strip() if os.path.exists(".last_db") else ""
    except OSError:
        last = ""
    if last and os.path.normcase(last) != os.path.normcase(here) and not os.path.isdir(last):
        raise SystemExit(f"STOP: your database folder {last} is not available now (is the E: drive connected?). I will NOT create a new empty database in {here}. "
                         f"Reconnect the drive and run again, or choose another place with  --db PATH  /  the EVE_PROFIT_DB environment variable. "
                         f"To start fresh on purpose, delete the file .last_db in the project folder.")
    if os.path.isdir(here):
        try:
            open(".last_db", "w", encoding="utf-8").write(here)
        except OSError:
            pass


@dataclass
class Profile:
    """What the planner knows about you. Stage 3 fills this from ESI."""
    ship_name: str = "Generic hauler"
    current_system: str = "Home"
    home_location_id: int = 0          # your clone/home station or structure (sync reads it; needs the clones permission)
    home_location_type: str = ""      # "station" (NPC, free) or "structure" (player-owned: may charge docking fees and taxes)
    current_location_id: int = 0      # station/structure you are docked in (sync sets; 0 = unknown/undocked)
    cargo_m3: float = 5000.0          # general cargo
    ore_hold_m3: float = 0.0          # 0 -> mining uses cargo_m3
    ship_value_isk: float = 20_000_000.0
    wallet_isk: float = 50_000_000.0
    max_jumps: int = 2                # search radius from current system
    secs_per_jump: float = 120.0      # align + warp + gate + dock + `next`: your timed flights run 1-3 minutes a jump
    autopilot: bool = False           # autopilot is slower and riskier
    dock_overhead_s: float = 60.0
    trade_overhead_s: float = 90.0
    mining_yield_m3_s: float = 0.0    # 0 = cannot mine
    minable_ores: list = field(default_factory=list)
    accounting_level: int = 4         # sales tax reduction
    sales_tax_base: float = 0.075     # base before Accounting; in-game check: Accounting V shows 3.37% (7.5% x 0.45)
    industry_level: int = 5           # skill 3380: -4% build time/level
    adv_industry_level: int = 3       # skill 3388: -3% build time/level
    mfg_slots_total: int = 1          # 1 + Mass Production + Advanced Mass Production (sync sets)
    mfg_slots_used: int = 0           # manufacturing jobs currently running (sync sets)
    max_runs: int = 10                # runs per batch considered
    job_fee_rate: float = 0.05        # fee on estimated item value (SCC 4% + system index); verify
    assume_all_blueprints: bool = False  # True = rank every buildable item (what to buy a BP for)
    combat_dps: float = 0.0           # your ship's real DPS; 0 = no combat
    ship_type_id: int = 0             # sync sets this; used to price hull replacement
    ship_ehp: float = 0.0             # your fit's effective HP (shield+armor+hull); 0 = unknown -> no combat
    ship_tank_dps: float = 0.0        # sustained effective repair per second
    fit_value_isk: float = 0.0        # modules/rigs you'd also lose with the hull
    insurance_payout_isk: float = 0.0
    min_win_margin: float = 3.0       # ship_ehp / expected damage taken; >=3 = "very likely wins"
    risky_win_margin: float = 1.5     # below min but >= this only if one session's profit repays the ship
    can_salvage: bool = False         # salvager fitted
    salvage_wreck_seconds: float = 25.0
    use_structures: bool = True       # scan player-structure markets (needs login + docking access)
    structure_ids: list = field(default_factory=list)   # extra structure ids to always scan (e.g. your home citadel)
    listing_tax: float = 0.05         # "Exordium Market Tax" (Market Safety Tax): 5.0% of the order value, charged when you LIST (seen 2026-10-10, not in the ESI journal); instant sales never pay it. Assumed for every region until verified elsewhere
    broker_fee: float = 0.03          # NPC station base; sync lowers it with Broker Relations (~0.3% per level, verify)
    structure_sales_tax: float = 0.01  # extra tax set by structure owners; varies per structure - verify
    away_mode: bool = False           # unattended: long autopilot hauls on strictly safe routes (or run with --away)
    away_max_jumps: int = 15          # how far a delivery may go while you are away
    pickup_jumps: int = 0             # how far to go to PICK UP goods (0 = max_jumps); away mode uses 3
    consider_ship_swaps: bool = True  # also rank "go to another ship, swap, then do X"
    swap_overhead_s: float = 120.0    # dock, swap ship, undock
    ships: dict = field(default_factory=dict)   # per-hull stats, e.g. {"Vexor": {"combat_dps": 300, "ship_ehp": 40000, "ship_tank_dps": 150, "ship_value_isk": 15000000, "cargo_m3": 500}}
    avoid_yellow: bool = True         # soft avoid
    min_profit_isk: float = 1.0      # owner 2026-10-24: no flat ISK minimum; ISK/hr with the time counted decides
    min_margin: float = 0.03

    @property
    def pickup(self) -> int:
        return self.pickup_jumps or self.max_jumps

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
            if known.get("sales_tax_base") in (0.045, 0.05):        # old default, wrong since the in-game check
                known["sales_tax_base"] = 0.075
            if known.get("secs_per_jump") == 45.0:                  # old default: your timed flights run 1-3 minutes a jump
                known["secs_per_jump"] = 120.0
            return cls(**known)
        return cls()

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)
