"""Once a day (hourly.bat): has CCP published new static game data (a patch: agents, items, blueprints, skills)? If so, download it and reload,
so agents CCP removed or moved leave the plan and new items join it. Prints one line; quiet when nothing changed.
python scripts/sde_refresh.py [--force]"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from eve_profit.db import connect, get_meta, set_meta  # noqa: E402
from eve_profit.update import check_update  # noqa: E402

DB = os.environ.get("EVE_PROFIT_DB") or "E:/EveProfit/eve_profit_dahl.db"
con = connect(DB)
last = float(get_meta(con, "sde_checked") or 0)
if "--force" not in sys.argv and time.time() - last < 20 * 3600:
    sys.exit(0)
try:
    status, build = check_update(con)
except Exception as e:                                                  # noqa: BLE001
    print(f"sde_refresh: CCP's static-data page did not answer ({type(e).__name__}); tried again tomorrow")
    sys.exit(0)
set_meta(con, "sde_checked", str(time.time()))
con.commit()
if status == "same" and "--force" not in sys.argv:
    print(f"sde_refresh: game data up to date (build {build})")
    sys.exit(0)
print(f"sde_refresh: new game data (build {build}): reloading the universe (agents, items, blueprints, skills)...", flush=True)
r = subprocess.run([sys.executable, "-m", "eve_profit", "universe", "--force", "--db", DB], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
print("sde_refresh: " + ("done" if r.returncode == 0 else "reload FAILED, see below") + "\n" + (r.stdout + r.stderr)[-1500:])
