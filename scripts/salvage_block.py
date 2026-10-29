"""Turn the killboard wreck leads off or on.  python scripts/salvage_block.py on "reason"  |  off  |  (no argument: show)
On = data/salvage_block.json exists and `next` stops sending you to killboard wrecks (leads.py blocked())."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from eve_profit.leads import BLOCK, blocked  # noqa: E402

cmd = sys.argv[1].lower() if len(sys.argv) > 1 else ""
if cmd == "on":
    reason = " ".join(sys.argv[2:]) or "salvage failed"
    json.dump({"reason": reason, "since": time.strftime("%Y-%m-%d %H:%M")}, open(BLOCK, "w", encoding="utf-8"), indent=1)
elif cmd == "off" and os.path.exists(BLOCK):
    os.remove(BLOCK)
print(f"killboard wreck leads: OFF ({blocked()})" if blocked() else "killboard wreck leads: ON")
