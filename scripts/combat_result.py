"""Record a real fight so the combat model learns from it (combatcheck.calibrate): a win at a level lowers that level's guessed threat
until the winning fit passes the 99% rule; any loss at that level keeps the guesses.
python scripts/combat_result.py --level 1 --mission "The Guristas Spies" --dps 18.5 --ehp 4149 [--tank 0] [--lost] [--no-finish]"""
import argparse
import json
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from eve_profit import combatcheck  # noqa: E402
from finish import finish  # noqa: E402

a = argparse.ArgumentParser()
a.add_argument("--level", required=True)
a.add_argument("--mission", required=True)
a.add_argument("--dps", type=float, required=True)
a.add_argument("--ehp", type=float, required=True)
a.add_argument("--tank", type=float, default=0.0)
a.add_argument("--lost", action="store_true")
a.add_argument("--no-finish", action="store_true")
o = a.parse_args()

res = combatcheck.results()
res.append({"date": date.today().isoformat(), "level": o.level, "mission": o.mission, "dps": o.dps, "ehp": o.ehp, "tank": o.tank,
            "won": not o.lost})
os.makedirs(os.path.dirname(combatcheck.RESULTS), exist_ok=True)
with open(combatcheck.RESULTS, "w", encoding="utf-8") as f:
    json.dump(res, f, indent=1)
lvl = int(o.level) if o.level.isdigit() else o.level
req = combatcheck.LEVEL1 if lvl == 1 else {}
r = combatcheck.calibrate(lvl, dict(req), res) if req else {}
outcome = "LOST" if o.lost else "won"
print(f"recorded: L{o.level} '{o.mission}' {outcome} with {o.dps:g} DPS / {o.ehp:,.0f} EHP"
      + (f"; level {o.level} now: threat {r['threat_dps']:.1f} DPS, min {r['min_dps']:g} DPS ({r.get('calibrated', 'guessed numbers kept')})" if r else ""))
if not o.no_finish:
    finish(f"Combat result: L{o.level} {o.mission} {outcome}",
           f"{date.today().isoformat()}: real fight L{o.level} '{o.mission}' {outcome} with {o.dps:g} DPS / {o.ehp:,.0f} EHP; combat model calibrated from it.")
