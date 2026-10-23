"""The game's wallet reaches the tool up to an hour late (ESI), so a buy or sale you just made is missing from the plan. Copy the new rows in the
game (Wallet > Market Transactions: select the rows, Ctrl+C) and run:  python scripts/wallet_paste.py
It reads the clipboard (or a file: --file rows.txt), finds item, quantity and buy/sell in each row and records them at once: buys count as held
(acquire.confirm), sales leave the stock (invoverlay.mark_opened). The real wallet replaces this when ESI catches up."""
import os
import re
import sqlite3
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from eve_profit import acquire, invoverlay  # noqa: E402

if "--file" in sys.argv:
    text = open(sys.argv[sys.argv.index("--file") + 1], encoding="utf-8").read()
else:                                                                    # the clipboard, read in-process (a child PowerShell hung on a busy PC, 2026-10-22)
    text = ""
    try:
        import tkinter
        _tk = tkinter.Tk()
        _tk.withdraw()
        text = _tk.clipboard_get()
        _tk.destroy()
    except Exception:                                                   # noqa: BLE001
        try:
            text = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=10).stdout
        except Exception:                                               # noqa: BLE001
            sys.exit("Could not read the clipboard. Paste the rows into a file and run:  python scripts/wallet_paste.py --file rows.txt")
con = sqlite3.connect(os.environ.get("EVE_PROFIT_DB") or "E:/EveProfit/eve_profit_dahl.db")
names = sorted((r[0] for r in con.execute("SELECT name FROM types WHERE name IS NOT NULL")), key=len, reverse=True)
by_lower = {n.lower(): n for n in names}
done = []
for ln in text.splitlines():
    if not re.search(r"\d{4}[.\-/]\d{2}[.\-/]\d{2}", ln):
        continue                                                         # not a transaction row
    low = ln.lower()
    item = next((by_lower[n.lower()] for n in names if len(n) > 3 and n.lower() in low), None)
    if not item:
        continue
    cells = [c.strip() for c in re.split(r"\t|\s{2,}", ln) if c.strip()]
    nums = [c for c in cells if re.fullmatch(r"-?[\d,]+(\.\d+)?( ISK)?", c)]
    qty = next((int(c.replace(",", "")) for c in nums if re.fullmatch(r"[\d,]+", c)), 1)
    neg = any(c.startswith("-") for c in nums) or re.search(r"\bbuy\b|bought", low)
    if neg:
        done.append(acquire.confirm(con, item, qty))
    else:
        done.append(invoverlay.mark_opened(con, item, qty).replace("(opened/used)", "(sold)"))
print("\n".join(done) or "No transaction rows found: in the game select the rows in Wallet > Market Transactions, Ctrl+C, then run this again.")
