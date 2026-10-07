"""`status`: where everything is stored and what is in it, so nothing ever seems lost."""
import glob
import os
import sqlite3
import time

KEY_TABLES = [("orders", "market orders (last scan)"), ("inventory", "your hangar stacks"), ("character_skills", "your skills"),
              ("skill_queue", "skill queue"), ("transactions", "your wallet trades (cost basis)"), ("standings", "agent/corp standings"),
              ("lp_balance", "loyalty-point balances"), ("agents", "mission agents (from the game data)"),
              ("activity_log", "timed runs (start/stop/log)"), ("my_blueprints", "your blueprints"), ("types", "items in the game data")]


def report(con, db_path, profile_path):
    L = [f"Database for this character: {db_path}  ({os.path.getsize(db_path) / 1e6:,.1f} MB)" if os.path.exists(db_path) else f"Database: {db_path} (not found)",
         f"Profile: {profile_path}  ({'found' if os.path.exists(profile_path) else 'not found'})", ""]
    L.append("What is stored:")
    for t, what in KEY_TABLES:
        try:
            n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except sqlite3.Error:
            n = "?"
        L.append(f"   {t:<18} {n:>10}  {what}")
    try:
        t = con.execute("SELECT MAX(fetched_at) FROM orders").fetchone()[0]
        L.append(f"\nLast market download: {time.strftime('%Y-%m-%d %H:%M', time.localtime(t))} ({(time.time() - t) / 3600:.1f} h ago)" if t else
                 "\nNo market download yet for this character: run  scan --live")
    except sqlite3.Error:
        pass
    rows = con.execute("SELECT activity,isk,hours,ship,ts FROM activity_log ORDER BY ts DESC LIMIT 8").fetchall()
    if rows:
        L.append("\nYour latest timed runs (all of them: `activities`):")
        for r in rows:
            L.append(f"   {time.strftime('%m-%d %H:%M', time.localtime(r['ts']))}  {r['activity']:<32} {r['isk']:>14,.0f} ISK in {r['hours']:.2f} h  {r['ship'] or ''}")
    else:
        L.append("\nNo timed runs saved yet for this character (start ... stop saves one each time).")
    d = os.path.dirname(db_path)
    L.append("\nAll character databases on disk:")
    for f in sorted(glob.glob(os.path.join(d, "eve_profit*.db"))):
        L.append(f"   {f}  {os.path.getsize(f) / 1e6:,.1f} MB")
    L.append("\nLogins and profiles (in the repo folder): " + ", ".join(sorted(glob.glob("tokens*.json") + glob.glob("profile*.json"))))
    hist = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "PowerShell", "PSReadLine", "ConsoleHost_history.txt")
    L.append(f"\nEvery command you typed in PowerShell is saved in:\n   {hist}\n   (open it in Notepad, or:  Get-Content \"{hist}\" | Select-String eve_profit )")
    return "\n".join(L)
