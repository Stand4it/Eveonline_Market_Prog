"""`careers`: every timed run grouped by career path (Industrialist, Explorer, Soldier of Fortune, Enforcer, Mining, Trading,
Science...): runs, hours, ISK/hr and ISK per active minute, which careers are still UNMEASURED, and which to try next.
Fewer than 3 runs = a guess, not a measurement."""
KNOWN = ["Industrialist", "Explorer", "Soldier of Fortune", "Enforcer", "Mining", "Trading", "Project Discovery"]
RULES = [("project discovery", "Project Discovery"), ("mixed", "Agent (several careers mixed)"),
         ("cap booster", "Industrialist"), ("armor repairer", "Industrialist"), ("shuttle", "Industrialist"), ("navitas", "Industrialist"),
         ("decoy", "Industrialist"), ("industrialist", "Industrialist"), ("entrepreneur", "Industrialist"),
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


def _career(o):
    """Career of an agent offer: its 'career' field, else the word in brackets after the agent name."""
    if o.get("career"):
        return o["career"]
    ag = o["agent"]
    return ag[ag.index("(") + 1:].rstrip(")").split(" - ")[0].split(",")[0].strip() if "(" in ag else ag


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
        def offer_for(k):
            for o in offers or []:
                if o.get("available", True) and _career(o) == k:
                    return o
            return None
        pick = next((k for k in missing if offer_for(k)), missing[0])      # prefer an unmeasured career you can start right now
        o = offer_for(pick)
        extra = f" (open now: {o['agent'].split(' (')[0]} - {o['mission'][:60]})" if o else " (no open offer for it right now)"
        tip.append(f"TRY NEXT: {pick}{extra}. An unmeasured career teaches the model more than repeating one you know.")
    thin = [n for n, c in ranked if c["runs"] < MIN_RUNS]
    if thin:
        tip.append(f"NEEDS MORE RUNS before it can be trusted: {', '.join(thin)}.")
    solid = [(n, c) for n, c in ranked if c["runs"] >= MIN_RUNS and "mixed" not in n]
    single = [(n, c) for n, c in ranked if "mixed" not in n]
    if solid:
        n, c = solid[0]
        tip.append(f"BEST MEASURED: {n} at {c['isk'] / c['hours']:,.0f} ISK/hr over {c['runs']} runs.")
    elif single:
        n, c = single[0]
        tip.append(f"BEST SO FAR (too few runs to trust): {n} at {c['isk'] / c['hours']:,.0f} ISK/hr.")
    return "\n".join(L + tip) if rows else "No timed runs yet. Use start --activity \"NAME\" and stop (see `next`)."
