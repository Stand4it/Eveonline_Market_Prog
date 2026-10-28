"""Check that expired offers left no prep steps behind (owner 2026-10-28).
Prints: open offers with no 'Seen' date (they never age out), and every line of the prep tree that still names an agent
whose offers are all closed.  usage: python scripts/offer_prep_audit.py"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main():
    offers = json.load(open(os.path.join(ROOT, "agent_offers.json"), encoding="utf-8"))["offers"]
    name = lambda o: (o.get("agent") or "").split(" (")[0]
    open_ = [o for o in offers if o.get("available", True)]
    live = {name(o) for o in open_}
    dead = {name(o) for o in offers if not o.get("available", True)} - live - {""}
    undated = [o for o in open_ if not o.get("accepted") and not re.search(r"Seen \d{4}-\d{2}-\d{2}", o.get("note", "") or "")]
    print(f"offers: {len(offers)}, open {len(open_)}, closed agents {len(dead)}")
    print(f"open + not accepted + no Seen date ({len(undated)}): they never expire by age")
    for o in undated:
        print(f"   {name(o)} | {(o.get('mission') or '')[:70]}")
    import subprocess
    text = subprocess.run([sys.executable, "-m", "eve_profit", "preptree"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    hits = [ln for ln in text.splitlines() if any(a and a in ln for a in dead)]
    print(f"prep tree lines naming a closed agent ({len(hits)}):")
    for ln in hits:
        print("   " + ln.strip()[:150])


if __name__ == "__main__":
    main()
