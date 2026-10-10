"""`careers`: every timed run grouped by career path (Industrialist, Explorer, Soldier of Fortune, Enforcer, Mining, Trading,
Science...): runs, hours, ISK/hr and ISK per active minute, which careers are still UNMEASURED, and which to try next.
Fewer than 3 runs = a guess, not a measurement."""
KNOWN = ["Industrialist", "Explorer", "Soldier of Fortune", "Enforcer", "Mining", "Trading", "Project Discovery"]
RULES = [("project discovery", "Project Discovery"), ("industrialist", "Industrialist"), ("entrepreneur", "Industrialist"),
         ("producer", "Industrialist"), ("courier", "Industrialist"), ("explorer", "Explorer"), ("data site", "Explorer"),
         ("relic", "Explorer"), ("soldier", "Soldier of Fortune"), ("enforcer", "Enforcer"), ("mining", "Mining"), ("mine ", "Mining"),
         ("market", "Trading"), ("trade", "Trading"), ("hauling", "Trading"), ("skills", "Skills")]
MIN_RUNS = 3


def career_of_activity(name):
    low = name.lower()
    for key, career in RULES:
        if key in low:
            return career
    return name


def report(con, offers=None):
    rows = con.execute("SELECT activity,isk,hours,ts FROM activity_log WHERE hours>0").fetchall()
    by = {}
    for r in rows:
        c = by.setdefault(career_of_activity(r["activity"]), {"runs": 0, "isk": 0.0, "hours": 0.0, "best": 0.0, "last": 0.0})
        c["runs"] += 1
        c["isk"] += r["isk"]
        c["hours"] += r["hours"]
        c["best"] = max(c["best"], r["isk"] / r["hours"])
        c["last"] = max(c["last"], r["ts"] or 0)
    L = [f"{'career':<20} {'runs':>4} {'hours':>6} {'ISK/hr':>12} {'ISK/min':>9} {'best run ISK/hr':>16}  status"]
    ranked = sorted(by.items(), key=lambda kv: -(kv[1]["isk"] / kv[1]["hours"]))
    for name, c in ranked:
        rate = c["isk"] / c["hours"]
        L.append(f"{name:<20} {c['runs']:>4} {c['hours']:>6.1f} {rate:>12,.0f} {rate / 60:>9,.0f} {c['best']:>16,.0f}  "
                 + ("MEASURED" if c["runs"] >= MIN_RUNS else f"{c['runs']} run(s): needs {MIN_RUNS - c['runs']} more"))
    missing = [k for k in KNOWN if k not in by]
    for k in missing:
        L.append(f"{k:<20} {0:>4} {'-':>6} {'-':>12} {'-':>9} {'-':>16}  UNMEASURED")
    L.append("")
    tip = []
    if missing:
        offer = ""
        for o in offers or []:
            if o.get("available", True) and o["agent"].split("(")[-1].rstrip(")").split(" - ")[0].split(",")[0].strip() in missing:
                offer = f" (open now: {o['agent'].split(' (')[0]} - {o['mission'][:60]})"
                break
        tip.append(f"TRY NEXT: {missing[0]}{offer}. An unmeasured career teaches the model more than repeating one you know.")
    thin = [n for n, c in ranked if c["runs"] < MIN_RUNS]
    if thin:
        tip.append(f"NEEDS MORE RUNS before it can be trusted: {', '.join(thin)}.")
    if ranked:
        n, c = ranked[0]
        tip.append(f"BEST SO FAR: {n} at {c['isk'] / c['hours']:,.0f} ISK/hr ({c['runs']} run(s)).")
    return "\n".join(L + tip) if rows else "No timed runs yet. Use start --activity \"NAME\" and stop (see `next`)."
