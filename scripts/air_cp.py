"""Update AIR Career points from the career screen in one call.
python scripts/air_cp.py Enforcer=175 Explorer=230 Industrialist=305 Soldier=65 [--no-finish]
Prints the changes and the overall total, logs DECISIONS.md, commits and pushes (scripts/finish.py)."""
import json
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from finish import finish  # noqa: E402

p = os.path.join(ROOT, "air_career.json")
d = json.load(open(p, encoding="utf-8"))
careers = d["careers"]
changes = []
for arg in (x for x in sys.argv[1:] if "=" in x):
    k, v = arg.split("=", 1)
    name = next((c for c in careers if c.lower().startswith(k.lower())), None)
    if not name:
        sys.exit(f"unknown career {k}; known: {', '.join(careers)}")
    old, new = careers[name]["cp"], int(v)
    if old != new:
        careers[name]["cp"] = new
        careers[name]["note"] += f" Update {date.today()}: {new} CP (was {old}, {new - old:+d})."
        changes.append(f"{name} {new} (was {old}, {new - old:+d})")
total = sum(c["cp"] for c in careers.values())
of = sum(c["of"] for c in careers.values())
print("changed:", "; ".join(changes) or "nothing")
print(f"overall: {total}/{of} CP")
if changes:
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(d, f, indent=1, ensure_ascii=False)
        f.write("\n")
    if "--no-finish" not in sys.argv:
        finish("AIR career: " + ", ".join(c.split(" (")[0] for c in changes),
               f"air_career.json: {'; '.join(changes)}; {total}/{of} overall.")
