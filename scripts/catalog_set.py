"""Change one activity in activity_catalog.json: python scripts/catalog_set.py <id or name part> key=value ... [--drop key]
Values: numbers and true/false are converted; 'null' deletes the key."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
p = os.path.join(ROOT, "activity_catalog.json")
d = json.load(open(p, encoding="utf-8"))
L = d if isinstance(d, list) else d["activities"]
key = sys.argv[1].lower()
hits = [a for a in L if a["id"].lower() == key] or [a for a in L if key in a["id"].lower() or key in a["name"].lower()]
if len(hits) != 1:
    sys.exit(f"{len(hits)} activities match '{sys.argv[1]}': {[a['id'] for a in hits]}")
a = hits[0]
for kv in sys.argv[2:]:
    k, v = kv.split("=", 1)
    if v == "null":
        a.pop(k, None)
        continue
    v = {"true": True, "false": False}.get(v.lower(), v)
    if isinstance(v, str):
        try:
            v = float(v) if "." in v else int(v)
        except ValueError:
            pass
    a[k] = v
with open(p, "w", encoding="utf-8", newline="\n") as f:
    json.dump(d, f, indent=1, ensure_ascii=False)
    f.write("\n")
print(a["id"], {k: a.get(k) for k in [x.split("=", 1)[0] for x in sys.argv[2:]]})
