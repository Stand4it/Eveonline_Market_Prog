"""FIT DATABASE from the killboard (owner 2026-10-30): "get fits for the ships that won engagements and fits that lost, and build a list of components and
fits that seem to work better than others", for EVERY hull (one day you can fly them all).
Source: EVE Ref's daily dump of every public killmail (https://data.everef.net/killmails/YYYY/killmails-YYYY-MM-DD.tar.bz2, ~2 MB, ~14,000 kills a day):
one download a day instead of one zKillboard call per kill. A killmail shows the FULL fit of the ship that DIED only; for the winners it shows just
their hull and the weapon they fired. So:
   fit_loss    hull + fitted modules of every loss, counted by who killed it: NPCs (the PvE risk), players (PvP), CONCORD (a ganker's own loss: ignored)
   fit_module  the same counts per hull + module (which modules show up in losses to NPCs more than the hull's average)
   fit_win     hull + weapon of every player on a kill (and how many of those were solo kills)
Survivors leave no killmail: 'rarely dies to NPCs' means rarely compared with how often it dies to players (a sign it is flown a lot), not proven safe.
python -m eve_profit fits [--item HULL]     the fits and modules for a hull (default: the ship you fly), marked when you have the skills
python -m eve_profit grabs --all             pulls the days not read yet (also runs on its own once a day)"""
import io
import json
import tarfile
import time
import urllib.request

URL = "https://data.everef.net/killmails/{y}/killmails-{d}.tar.bz2"
UA = "eve_profit (personal EVE Online helper; contact via the EVE character Stand4it Dahl)"
CONCORD = 1000125                                                       # a CONCORD kill is a suicide ganker's own loss: says nothing about the fit
CAPSULES = {670, 33328}
SLOT = {**{f: "low" for f in range(11, 19)}, **{f: "mid" for f in range(19, 27)}, **{f: "high" for f in range(27, 35)},
        **{f: "rig" for f in range(92, 100)}, **{f: "sub" for f in range(125, 133)}}
FIT_CATS = (7, 32)                                                      # modules and subsystems (charges in a gun are category 8: not part of the fit)
FIRST_DAYS = 30
MIN_LOSSES = 3


def ensure(con):
    con.execute("CREATE TABLE IF NOT EXISTS fit_loss(hull INTEGER, fit TEXT, npc INTEGER DEFAULT 0, pvp INTEGER DEFAULT 0, concord INTEGER DEFAULT 0, "
                "last_day TEXT, sample INTEGER, PRIMARY KEY(hull, fit))")
    con.execute("CREATE TABLE IF NOT EXISTS fit_module(hull INTEGER, type_id INTEGER, npc INTEGER DEFAULT 0, pvp INTEGER DEFAULT 0, PRIMARY KEY(hull, type_id))")
    con.execute("CREATE TABLE IF NOT EXISTS fit_win(ship INTEGER, weapon INTEGER, kills INTEGER DEFAULT 0, solo INTEGER DEFAULT 0, PRIMARY KEY(ship, weapon))")


def _days_done(con):
    try:
        r = con.execute("SELECT value FROM meta WHERE key='fitdb_days'").fetchone()
        return set(json.loads(r[0])) if r else set()
    except Exception:                                                   # noqa: BLE001
        return set()


def parse_day(blob, cats):
    """One day's dump (bytes) -> (losses {(hull, fit): [npc, pvp, concord, sample]}, modules {(hull, tid): [npc, pvp]}, wins {(ship, weapon): [kills, solo]})."""
    loss, mods, wins = {}, {}, {}
    t = tarfile.open(fileobj=io.BytesIO(blob), mode="r|bz2")
    for m in t:
        if not m.isfile():
            continue
        try:
            d = json.load(t.extractfile(m))
        except ValueError:
            continue
        v = d.get("victim", {})
        hull = v.get("ship_type_id")
        if cats.get(hull) != 6 or hull in CAPSULES:
            continue                                                    # structures, deployables, pods
        att = d.get("attackers", [])
        players = [a for a in att if a.get("character_id")]
        kind = 1 if players else (2 if any(a.get("corporation_id") == CONCORD for a in att) else 0)   # 0 npc, 1 pvp, 2 concord
        fit = {}
        for it in v.get("items", []):
            if it.get("flag") in SLOT and cats.get(it.get("item_type_id")) in FIT_CATS:
                q = int(it.get("quantity_dropped", 0) or 0) + int(it.get("quantity_destroyed", 0) or 0)
                fit[it["item_type_id"]] = fit.get(it["item_type_id"], 0) + max(q, 1)
        key = (hull, " ".join(f"{k}*{fit[k]}" for k in sorted(fit)))
        row = loss.setdefault(key, [0, 0, 0, d.get("killmail_id")])
        row[kind] += 1
        if kind < 2:
            for tid in fit:
                mods.setdefault((hull, tid), [0, 0])[kind] += 1
        for pair in {(a.get("ship_type_id"), a.get("weapon_type_id")) for a in players if cats.get(a.get("ship_type_id")) == 6}:
            w = wins.setdefault(pair, [0, 0])
            w[0] += 1
            w[1] += 1 if len(players) == 1 else 0
    return loss, mods, wins


def _store(con, day, loss, mods, wins):
    if not con.in_transaction:
        con.execute("BEGIN IMMEDIATE")                                  # one short write: the parsing above held no lock
    con.executemany("INSERT INTO fit_loss(hull, fit, npc, pvp, concord, last_day, sample) VALUES(?,?,?,?,?,?,?) ON CONFLICT(hull, fit) DO UPDATE SET "
                    "npc=npc+excluded.npc, pvp=pvp+excluded.pvp, concord=concord+excluded.concord, last_day=MAX(last_day, excluded.last_day), sample=excluded.sample",
                    [(h, f, a, b, c, day, s) for (h, f), (a, b, c, s) in loss.items()])
    con.executemany("INSERT INTO fit_module(hull, type_id, npc, pvp) VALUES(?,?,?,?) ON CONFLICT(hull, type_id) DO UPDATE SET npc=npc+excluded.npc, pvp=pvp+excluded.pvp",
                    [(h, t, a, b) for (h, t), (a, b) in mods.items()])
    con.executemany("INSERT INTO fit_win(ship, weapon, kills, solo) VALUES(?,?,?,?) ON CONFLICT(ship, weapon) DO UPDATE SET kills=kills+excluded.kills, solo=solo+excluded.solo",
                    [(s, w, a, b) for (s, w), (a, b) in wins.items() if s and w])
    done = sorted(_days_done(con) | {day})
    con.execute("INSERT OR REPLACE INTO meta VALUES('fitdb_days', ?)", (json.dumps(done),))
    con.commit()


def ingest(con, days=FIRST_DAYS, now=None, fetch=None, log=None):
    """Read every day of the last `days` (yesterday back) that is not in the database yet. -> (days read, losses counted)."""
    ensure(con)
    con.commit()
    fetch = fetch or (lambda url: urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60).read())
    cats = dict(con.execute("SELECT type_id, category_id FROM types"))
    done, now = _days_done(con), now or time.time()
    n_days = n_loss = 0
    for i in range(1, days + 1):
        day = time.strftime("%Y-%m-%d", time.gmtime(now - i * 86400))
        if day in done:
            continue
        try:
            blob = fetch(URL.format(y=day[:4], d=day))
        except Exception as e:                                          # noqa: BLE001
            if log:
                log(f"   {day}: not available ({type(e).__name__})")
            continue
        loss, mods, wins = parse_day(blob, cats)
        _store(con, day, loss, mods, wins)
        n_days += 1
        n_loss += sum(r[0] + r[1] + r[2] for r in loss.values())
        if log:
            log(f"   {day}: {sum(r[0] + r[1] + r[2] for r in loss.values()):,} ship losses")
    return n_days, n_loss


def grab(con):
    """For grabs.py: the days not read yet (a few back, so a missed day is caught up)."""
    first = not _days_done(con)
    n, k = ingest(con, FIRST_DAYS if first else 4)
    return f"{n} day(s) of killmails read, {k:,} ship losses (fits for every hull)", (0.1 if n else 0.0), None


def type_id(con, name):
    r = con.execute("SELECT type_id FROM types WHERE name=? COLLATE NOCASE", (name,)).fetchone()
    return int(r[0]) if r else None


def usable(con, tid, have=None):
    """(True, '') when your skills cover the type's required skills (no skills synced: True), else (False, 'Skill N (have M), ...')."""
    from . import skills
    have = skills.have(con) if have is None else have
    if not have:
        return True, ""
    miss = skills.type_missing(con, int(tid), have)
    return (not miss), (skills.explain(con, miss) if miss else "")


def npc_share(npc, pvp):
    """Smoothed share of a fit's losses that were to NPCs (lower = it survives PvE better for how often it is flown)."""
    return (npc + 1.0) / (npc + pvp + 2.0)


def module_risk(con, hull):
    """{type_id: factor >= 1}: how much more often a module shows up in this hull's NPC losses than the hull's own average (1 = no worse; few losses: 1)."""
    try:
        rows = con.execute("SELECT type_id, npc, pvp FROM fit_module WHERE hull=?", (hull,)).fetchall()
        tot = con.execute("SELECT TOTAL(npc), TOTAL(pvp) FROM fit_loss WHERE hull=?", (hull,)).fetchone()
    except Exception:                                                   # noqa: BLE001
        return {}
    base = npc_share(*(tot or (0, 0)))
    return {t: max(1.0, npc_share(a, b) / base) for t, a, b in rows if a + b >= 10}


def best_fits(con, hull, limit=5, have=None):
    """Fits of `hull` that rarely die to NPCs, most-flown first among equals: [{fit [(name, qty, tid)], npc, pvp, share, ok, missing, cost}]."""
    from . import skills
    have = skills.have(con) if have is None else have
    names = dict(con.execute("SELECT type_id, name FROM types"))
    price = dict(con.execute("SELECT type_id, adjusted_price FROM prices"))
    rows = con.execute("SELECT fit, npc, pvp FROM fit_loss WHERE hull=? AND fit<>'' AND npc+pvp>=?", (hull, MIN_LOSSES)).fetchall()
    rows.sort(key=lambda r: (npc_share(r[1], r[2]), -(r[1] + r[2])))
    out = []
    for fit, npc, pvp in rows[:limit]:
        items = [(int(t), int(q)) for t, q in (x.split("*") for x in fit.split())]
        miss = [m for t, _q in items for m in [usable(con, t, have)[1]] if m]
        out.append({"fit": [(names.get(t, str(t)), q, t) for t, q in items], "npc": npc, "pvp": pvp, "share": npc_share(npc, pvp),
                    "ok": not miss and usable(con, hull, have)[0], "missing": "; ".join(sorted(set(miss))),
                    "cost": float(price.get(hull) or 0) + sum(float(price.get(t) or 0) * q for t, q in items)})
    return out


def report(con, p, text=""):
    """Text for `python -m eve_profit fits [--item HULL]`."""
    ensure(con)
    hull_name = text or getattr(p, "ship_name", "") or ""
    hull = type_id(con, hull_name) if hull_name else None
    if not text and getattr(p, "ship_type_id", None):                  # the ship you fly: its TYPE, not the name you gave it
        hull = int(p.ship_type_id)
        hull_name = con.execute("SELECT name FROM types WHERE type_id=?", (hull,)).fetchone()[0]
    days = len(_days_done(con))
    if not days:
        return "No killmails read yet: python -m eve_profit grabs --all (reads the last 30 days, ~2 MB each)."
    if not hull:
        top = con.execute("SELECT t.name, SUM(f.npc), SUM(f.pvp) FROM fit_loss f JOIN types t ON t.type_id=f.hull GROUP BY f.hull ORDER BY SUM(f.npc) DESC LIMIT 10").fetchall()
        return "Hull not found. Most NPC losses: " + ", ".join(f"{n} ({a})" for n, a, _b in top)
    tot = con.execute("SELECT TOTAL(npc), TOTAL(pvp), TOTAL(concord) FROM fit_loss WHERE hull=?", (hull,)).fetchone()
    ok_hull, why = usable(con, hull)
    L = [f"KILLBOARD FITS for {hull_name} ({days} days of killmails): {tot[0]:,.0f} losses to NPCs, {tot[1]:,.0f} to players, {tot[2]:,.0f} to CONCORD (gankers, ignored)"
         + ("" if ok_hull else f"  [you cannot fly it yet: {why}]")]
    L.append("   Fits that rarely die to NPCs (share of their losses that were NPCs; survivors leave no killmail, so this is a hint, not proof):")
    for f in best_fits(con, hull):
        mods = ", ".join(f"{q} x {n}" for n, q, _t in sorted(f["fit"], key=lambda x: x[0]))
        tag = "YOU CAN FIT IT" if f["ok"] else f"needs {f['missing'][:90]}"
        L.append(f"     {100 * f['share']:4.0f}% NPC  ({f['npc']} NPC / {f['pvp']} PvP losses)  ~{f['cost']:,.0f} ISK  [{tag}]\n        {mods}")
    names = dict(con.execute("SELECT type_id, name FROM types"))
    risk = sorted(module_risk(con, hull).items(), key=lambda x: -x[1])[:5]
    if risk and risk[0][1] > 1.2:
        L.append("   Modules seen in NPC losses more than this hull's average (avoid for PvE): "
                 + ", ".join(f"{names.get(t, t)} x{r:.1f}" for t, r in risk if r > 1.2))
    wins = con.execute("SELECT weapon, kills, solo FROM fit_win WHERE ship=? ORDER BY kills DESC LIMIT 5", (hull,)).fetchall()
    if wins:
        L.append(f"   When a {hull_name} WINS (player kills it was on; winners' full fits are never on a killmail): "
                 + ", ".join(f"{names.get(w, w)} {k:,} ({s:,} solo)" for w, k, s in wins))
    return "\n".join(L)
