"""Set the in-game destination to a station (by name) or a system, through ESI (owner 2026-10-29: salvage steps point at the wrecks' station).
Autopilot then warps you there in the same system.  python scripts/set_dest.py "Jita IV - Moon 4 - Caldari Navy Assembly Plant"
ESI only accepts systems, stations and structures as destinations; for a gate or a moon, warp to it from the Overview."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from eve_profit import sso  # noqa: E402
from eve_profit.cli import resolve_client_id  # noqa: E402
from eve_profit.db import connect  # noqa: E402
from eve_profit.esi import ESI  # noqa: E402

name = " ".join(sys.argv[1:]).strip()
if not name:
    raise SystemExit(__doc__)
con = connect(os.environ.get("EVE_PROFIT_DB") or "E:/EveProfit/eve_profit_dahl.db")
r = con.execute("SELECT station_id FROM stations WHERE name=?", (name,)).fetchone() or \
    con.execute("SELECT system_id FROM systems WHERE name=?", (name,)).fetchone()
if not r:
    raise SystemExit(f"'{name}' is not a station or system I know. ESI cannot target gates or moons: warp to those from the Overview.")
esi = ESI()
esi.token, _ = sso.get_token(resolve_client_id())
esi.post("/ui/autopilot/waypoint/", destination_id=r[0], add_to_beginning="false", clear_other_waypoints="true")
print(f"DESTINATION SET: {name}. In the game: Route > autopilot (or right-click it > Warp to Within 0 m).")
