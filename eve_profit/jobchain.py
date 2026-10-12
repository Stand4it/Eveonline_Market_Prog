"""A freelance delivery job done from stock as ONE STEP AT A TIME: accept the job, load the goods, fly (one hop per step, destination set), deliver.
Only jobs paid from stock you already hold here (no buying) are offered; the extra over simply selling the stock must be worth the trip.
State in meta 'jobchain': {"id","name","item","units","stage"}."""
import json

KEY = "jobchain"
MIN_GAIN_HR = 100000.0
STICKY = 1.25


def _load(con):
    try:
        r = con.execute("SELECT value FROM meta WHERE key=?", (KEY,)).fetchone()
        return json.loads(r[0]) if r else None
    except Exception:                                                   # noqa: BLE001
        return None


def _save(con, st):
    if st is None:
        con.execute("DELETE FROM meta WHERE key=?", (KEY,))
    else:
        con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (KEY, json.dumps(st)))
    con.commit()


def _hop(g, p, systems):
    """(next system name toward the nearest of these systems, its distance, name) or None."""
    best = None
    for sid, nm in systems:
        try:
            r = g.route(g.id_of(p.current_system), sid, 60, p.avoid_yellow)
        except Exception:                                               # noqa: BLE001
            continue
        if r and (best is None or r.jumps < best[1]):
            best = (g.name[r.path[1]] if len(r.path) > 1 else None, r.jumps, nm)
    return best


def candidate(con, g, p):
    """(rate ISK/hr, step text) or None. The shown stage is remembered so `done` can advance it."""
    from .jobplan import options
    st = _load(con)
    rows = [r for r in options(con, g, p) if r["kind"] == "deliver" and r["from_stock"] == r["units"] and r["isk_hr"] >= MIN_GAIN_HR]
    row = None
    if st:
        row = next((r for r in rows if r["job"]["id"] == st["id"]), None)
        if row is None and st["stage"] != "deliver":                     # the job vanished or is no longer worth it
            _save(con, None)
            st = None
    if st is None:
        if not rows:
            return None
        row = rows[0]
        st = {"id": row["job"]["id"], "name": row["job"]["name"], "item": row["what"], "units": row["units"], "stage": "accept"}
        _save(con, st)
    if row is None:
        return None
    j = row["job"]
    rate = row["isk_hr"] * (STICKY if st["stage"] != "accept" else 1.0)
    target = _hop(g, p, j["broadcast"])
    if st["stage"] == "accept":
        text = "\n".join([f"STEP: ACCEPT FREELANCE JOB - {j['name'][:50]} (about 1 minute)",
                          f"   DO ONLY THIS: Neocom > Freelance Jobs > find '{j['name']}' ({j['corp']}) > Accept.",
                          f"   It pays {j['per_unit']:.2f} ISK per item; you will deliver {row['units']:,} x {row['what']} from your stock: {row['gain']:,.0f} ISK more than selling them.",
                          "   When it is accepted run:  python -m eve_profit done"])
    elif target and target[1] > 0:
        text = "\n".join([f"STEP: FLY to {target[0]}",
                          f"   DO ONLY THIS: load {row['units']:,} x {row['what']} into your ship if it is not loaded yet, then fly to {target[0]} and stop there. Then run  python -m eve_profit next.",
                          f"   LATER: deliver at {target[2]} ({target[1]} jumps from here): {j['name']}"])
    else:
        text = "\n".join([f"STEP: DELIVER {row['units']:,} x {row['what']} for the freelance job (about 3 minutes)",
                          f"   DO ONLY THIS: dock at one of the job's destination stations/structures in {target[2] if target else 'this system'}, then Neocom > Freelance Jobs > '{j['name']}' > Deliver.",
                          f"   It pays about {row['revenue']:,.0f} ISK. When it is done run:  python -m eve_profit done"])
    return rate, text


def mark_shown(con, text):
    first = (text or "").split("\n", 1)[0]
    st = _load(con)
    if not st:
        return
    st["shown"] = "accept" if first.startswith("STEP: ACCEPT FREELANCE JOB -") else ("deliver" if first.startswith("STEP: DELIVER ") else ("fly" if first.startswith("STEP: FLY to") else None))
    _save(con, st)


def done(con):
    """`done`: advance the stage that was shown. -> message or None."""
    st = _load(con)
    if not st or not st.get("shown"):
        return None
    if st["shown"] == "accept":
        st["stage"], st["shown"] = "fly", None
        _save(con, st)
        return f"OK, '{st['name'][:40]}' accepted. Run  python -m eve_profit next  for the first step toward the delivery."
    if st["shown"] == "deliver":
        _save(con, None)
        return "OK, delivered. Run  python -m eve_profit sync  then  next."
    return None
