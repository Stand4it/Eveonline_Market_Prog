"""`chars`: compare every character you have set up (main + each --char) so you can see which is the least built up."""
import glob
import json
import os
import sqlite3


def _one(label, db_path, profile_path):
    sp = lvls = 0
    try:
        c = sqlite3.connect(db_path)
        r = c.execute("SELECT COALESCE(SUM(sp),0), COUNT(*) FROM character_skills").fetchone()
        sp, lvls = r[0], r[1]
        bps = c.execute("SELECT COUNT(*) FROM my_blueprints").fetchone()[0]
        c.close()
    except sqlite3.Error:
        bps = 0
    prof = {}
    if os.path.exists(profile_path):
        with open(profile_path) as f:
            prof = json.load(f)
    return {"label": label, "sp": sp, "skills": lvls, "bps": bps, "wallet": prof.get("wallet_isk", 0),
            "ship": prof.get("ship_name", "?"), "where": prof.get("current_system", "?")}


def compare(main_db, main_profile="profile.json"):
    d = os.path.dirname(main_db)
    rows = []
    if os.path.exists(main_db):
        rows.append(_one("(main)", main_db, main_profile))
    for path in sorted(glob.glob(os.path.join(d, "eve_profit_*.db"))):
        name = os.path.basename(path)[len("eve_profit_"):-3]
        rows.append(_one(name, path, f"profile_{name}.json"))
    if not rows:
        return "No characters set up yet."
    rows.sort(key=lambda r: (r["sp"], r["wallet"]))
    L = [f"{'character':<12} {'skill pts':>12} {'skills':>6} {'BPs':>4} {'wallet ISK':>14}  {'ship':<22} where"]
    for r in rows:
        L.append(f"{r['label']:<12} {r['sp']:>12,.0f} {r['skills']:>6} {r['bps']:>4} {r['wallet']:>14,.0f}  {r['ship']:<22} {r['where']}")
    low = rows[0]
    L.append("")
    if len(rows) == 1:
        L.append("Only one character so far. Add one:  python -m eve_profit login --char NAME   (pick the character at the browser screen),")
        L.append("then  sync --char NAME.  Run `chars` again to compare.")
    else:
        L.append(f"Least built up (fewest skill points): {low['label']}. Start with:  python -m eve_profit now --char {low['label']}"
                 if low["label"] != "(main)" else "Least built up is your main database; use --char for the others.")
    return "\n".join(L)
