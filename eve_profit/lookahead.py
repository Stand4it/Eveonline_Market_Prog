"""The look-ahead planner: `next` does not only pick the best step NOW, it asks what pays most over the next several active hours.
 * Steps that can only be done once a day (AIR daily goals) go first, then the best repeatable step sets your BASE rate.
 * Every locked activity in activity_catalog.json is an UNLOCK option: train the missing skills (clock time, free while you keep working),
   buy the books, earn the ISK gap (while working at the base rate) - then it pays its own rate for the rest of the horizon.
   gain = (rate of the unlocked activity - base rate) x (hours left after it unlocks) - the books.
 * A free enabler (a skill you can queue right now) becomes a 30-second step in the chain, before the main step.
 * Unmodeled activities stay on the table: their prior is deliberately conservative until you time 3 runs.
Rates are per ACTIVE hour; training time runs on the clock in the background."""
import calendar
import time as _t

from .catalog import MODELED_RUNS, skill_levels, status

HORIZON_H = 6.0              # active hours the plan looks over
GUESS_SHARE = 0.35           # an unmodeled activity counts at low + 35% of the way to its high prior
DEFAULT_BASE = 300000.0      # base rate when no repeatable step is ranked yet
MIN_GAIN = 50000.0           # an unlock must beat this many ISK over the horizon to be mentioned


def act_rate(a):
    """(ISK per active hour, 'measured'|'guess') for a catalog activity."""
    if a.get("rate") and a.get("runs", 0) >= MODELED_RUNS:
        return float(a["rate"]), "measured"
    lo, hi = a["prior"]
    return lo + GUESS_SHARE * (hi - lo), "guess"


def chain_gain(base, rate_u, delay_h, horizon=HORIZON_H, cost=0.0):
    """ISK gained over the horizon by switching to an unlocked activity after delay_h hours (you earn the base rate while waiting)."""
    return (rate_u - base) * max(0.0, horizon - delay_h) - cost


def base_rate(cands):
    """Best REPEATABLE rate among the ranked steps (once-a-day and model-turn entries do not count)."""
    rates = [c[0] for c in cands if c[0] != float("inf") and "once a day" not in str(c[3])]
    return max(rates) if rates else DEFAULT_BASE


def _queue_hours(con, skill_name):
    """Hours until the skill_queue finishes the skill (0 if not queued)."""
    try:
        r = con.execute("SELECT MAX(q.finish_date) FROM skill_queue q JOIN types t ON t.type_id=q.skill_id WHERE t.name=? COLLATE NOCASE", (skill_name,)).fetchone()
        if r and r[0]:
            return max(0.0, (calendar.timegm(_t.strptime(r[0].rstrip("Z")[:19], "%Y-%m-%dT%H:%M:%S")) - _t.time()) / 3600.0)
    except Exception:                                                   # noqa: BLE001
        pass
    return 0.0


def load_unlocks():
    """unlocks.json: ships, gear and standings that unlock or boost activities (data, grows with the game)."""
    import json
    import os
    f = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "unlocks.json")
    try:
        return json.load(open(f, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _owned(con, item):
    """Do you hold this ship / item (hangar, parked ships or fitted)?  -> quantity."""
    n = 0
    for sql in ("SELECT COALESCE(SUM(i.quantity),0) FROM inventory i JOIN types t ON t.type_id=i.type_id WHERE t.name=? COLLATE NOCASE",
                "SELECT COUNT(*) FROM my_ships s JOIN types t ON t.type_id=s.type_id WHERE t.name=? COLLATE NOCASE",
                "SELECT COALESCE(SUM(f.quantity),0) FROM fitted f JOIN types t ON t.type_id=f.type_id WHERE t.name=? COLLATE NOCASE"):
        try:
            n += int(con.execute(sql, (item,)).fetchone()[0] or 0)
        except Exception:                                               # noqa: BLE001
            pass
    return n


def _price(con, g, p, item, est, qty=1):
    """Cost to buy qty of item: cheapest ask within 10 jumps -> (ISK, where, jumps, from_market); else the estimate."""
    try:
        row = con.execute("SELECT type_id FROM types WHERE name=? COLLATE NOCASE", (item,)).fetchone()
        if row:
            reach = g.reach(g.id_of(p.current_system), 10, p.avoid_yellow)
            best = None
            for sid, price in con.execute("SELECT system_id, MIN(price) FROM orders WHERE type_id=? AND is_buy=0 GROUP BY system_id", (row[0],)):
                if sid in reach and (best is None or price < best[0]):
                    best = (price, sid)
            if best:
                return best[0] * qty, g.name[best[1]], reach[best[1]].jumps, True
    except Exception:                                                   # noqa: BLE001
        pass
    return float(est) * qty, "", None, False


def standing_with(con, corp):
    """Best standing (-10..10) with any agent/corporation/faction whose name contains `corp`; None if unknown (sync fills the names)."""
    try:
        rows = con.execute("SELECT s.standing FROM standings s JOIN standing_names n ON n.from_id=s.from_id WHERE n.name LIKE ?", (f"%{corp}%",)).fetchall()
    except Exception:                                                   # noqa: BLE001
        return None
    return max((r[0] for r in rows), default=None)


def _skill_chain(con, g, p, goals):
    """Skills to train for `goals` [(name, level, why)] -> (train hours on the clock, book cost, book note, first queueable step) or None."""
    from .trainplan import book_list, plan_training, trainable_now
    if not goals:
        return 0.0, 0.0, "", None
    best = {}
    for sk, lvl, why in goals:
        if lvl > best.get(sk, (0, ""))[0]:
            best[sk] = (lvl, why)
    res = plan_training(con, 24 * 365, [(k, v[0], v[1]) for k, v in best.items()])
    if res["unknown"] or not res["steps"]:
        return None
    train_h = res["steps"][-1]["cum"] / 60.0
    try:
        books = book_list(con, g, p, res, hours=24 * 365)
    except Exception:                                                   # noqa: BLE001
        books = []
    cost, note = 0.0, ""
    for name, price, where, jumps in books:
        if price is None:
            note += f"{name} book: no seller found nearby; "
        else:
            cost += price
            note += f"{name} book ~{price:,.0f} at {where} ({jumps} jumps); "
    now = trainable_now(con, res)
    return train_h, cost, note.strip("; "), (now[0] if now else None)


def _missing_skills(con, req):
    """[(skill, level, queued_hours)] you do not have yet; queued ones carry the hours until the queue finishes them."""
    trained = skill_levels(con)
    try:
        virt = {r[0].lower(): r[1] for r in con.execute("SELECT t.name, s.level FROM character_skills s JOIN types t ON t.type_id=s.skill_id")}
        for r in con.execute("SELECT t.name, q.level FROM skill_queue q JOIN types t ON t.type_id=q.skill_id"):
            virt[r[0].lower()] = max(virt.get(r[0].lower(), 0), r[1])
    except Exception:                                                   # noqa: BLE001
        virt = trained
    out = []
    for sk, lvl in req.items():
        if trained.get(sk.lower(), 0) >= lvl:
            continue
        out.append((sk, lvl, _queue_hours(con, sk) if virt.get(sk.lower(), 0) >= lvl else None))
    return out


def unlock_options(con, g, p, base, horizon=HORIZON_H):
    """Every way to open a better activity as a chain of prerequisites: skills to train (clock time), ships and gear to buy, standing to earn
    by running agent missions, ISK to earn. Also BOOSTS: a ship or gear that makes an activity you can do pay more. Best gain first."""
    try:
        from .trainplan import plan_training  # noqa: F401  (import check)
    except Exception:                                                   # noqa: BLE001
        return []
    wallet = float(p.wallet_isk or 0.0)
    cat = {a["id"]: a for a in status(con, wallet)}
    data = load_unlocks()
    entries = ([{**e, "kind": "ship"} for e in data.get("ships", [])] + [{**e, "kind": "gear"} for e in data.get("gear", [])]
               + [{**e, "kind": "standing"} for e in data.get("standings", [])])

    def entry_need(e):
        """-> (cost, delay_h, goals, parts) for one entry, or None when it is already satisfied."""
        goals = [(sk, lvl, f"for {e.get('item', e.get('corp'))}") for sk, lvl, q in _missing_skills(con, e.get("requires", {})) if q is None]
        queue_h = max([q for _, _, q in _missing_skills(con, e.get("requires", {})) if q is not None], default=0.0)
        if e["kind"] == "standing":
            cur = standing_with(con, e["corp"])
            have = 0.0 if cur is None else cur
            if have >= e["needs"]:
                return None
            steps = -(-int(round((e["needs"] - have) * 1000)) // max(int(round(e["per_step"] * 1000)), 1))
            part = (f"standing with {e['corp']}: {'unknown (sync resolves the names), assuming 0' if cur is None else f'{cur:+.2f}'} -> {e['needs']:+.2f}: "
                    f"about {steps} Level 1 missions from that corp ({steps * e['minutes_per_step']:.0f} min of the work you would do anyway)")
            return 0.0, steps * e["minutes_per_step"] / 60.0, goals, [part], queue_h
        qty = int(e.get("qty", 1))
        have_n = _owned(con, e["item"])
        if have_n >= qty:
            return None
        cost, where, jumps, mkt = _price(con, g, p, e["item"], e.get("est_cost", 0), qty - have_n)
        part = f"buy {qty - have_n} x {e['item']} ~{cost:,.0f} ISK" + (f" at {where} ({jumps} jumps)" if where else " (estimate: not on the scanned market)")
        return cost, 0.25, goals, [part], queue_h

    out = []
    # 1. activities that are locked, or gated by a ship/gear/standing entry
    by_act = {}
    for e in entries:
        for aid in e.get("unlocks", []):
            by_act.setdefault(aid, []).append(e)
    for aid in sorted(set(by_act) | {k for k, a in cat.items() if not a["unlocked"] and not a.get("blocked")}):
        a = cat.get(aid)
        if not a or a.get("blocked"):
            continue
        goals = [(sk, lvl, f"unlocks {a['name']}") for sk, lvl, q in _missing_skills(con, a.get("requires", {})) if q is None]
        queue_h = max([q for _, _, q in _missing_skills(con, a.get("requires", {})) if q is not None], default=0.0)
        cost, delay_parts, parts = 0.0, [queue_h], []
        for e in by_act.get(aid, []):
            need = entry_need(e)
            if not need:
                continue
            c, d, gl, pt, qh = need
            cost += c
            delay_parts.append(d)
            delay_parts.append(qh)
            goals += gl
            parts += pt
        gap = max(0.0, float(a.get("isk_min", 0) or 0) - wallet)
        if a["unlocked"] and not parts:
            continue                                                    # open already and nothing to buy/earn
        try:
            chain = _skill_chain(con, g, p, goals)
        except Exception:                                               # noqa: BLE001
            chain = None
        if chain is None:
            continue
        train_h, books, book_note, enabler = chain
        rate_u, src = act_rate(a)
        delay_h = max(delay_parts + [train_h, gap / max(base, 1.0)])
        gain = chain_gain(base, rate_u, delay_h, horizon, cost + books)
        out.append({"id": aid, "kind": "unlock", "name": a["name"], "rate": rate_u, "src": src, "delay_h": delay_h, "train_h": train_h, "gap": gap,
                    "books_cost": books + cost, "book_note": book_note, "parts": parts, "gain": gain, "enabler": enabler})
    # 2. boosts: the same activity pays more with this ship or gear
    for e in entries:
        for aid, mult in (e.get("boosts") or {}).items():
            a = cat.get(aid)
            if not a or a.get("blocked"):
                continue
            need = entry_need(e)
            if not need:
                continue
            c, d, gl, pt, qh = need
            try:
                chain = _skill_chain(con, g, p, gl + [(sk, lvl, f"unlocks {a['name']}") for sk, lvl, q in _missing_skills(con, a.get("requires", {})) if q is None])
            except Exception:                                           # noqa: BLE001
                chain = None
            if chain is None:
                continue
            train_h, books, book_note, enabler = chain
            rate_u, src = act_rate(a)
            new_rate = rate_u * float(mult)
            delay_h = max(d, qh, train_h)
            gain = chain_gain(base, new_rate, delay_h, horizon, c + books)
            out.append({"id": e["id"], "kind": "boost", "name": f"{e.get('item', e.get('corp'))} -> {a['name']} x{mult}", "rate": new_rate, "src": src,
                        "delay_h": delay_h, "train_h": train_h, "gap": 0.0, "books_cost": books + c, "book_note": book_note, "parts": pt, "gain": gain,
                        "enabler": enabler})
    out.sort(key=lambda o: -o["gain"])
    return out


def deferred_modeling(con, g, p):
    """Modeling (test) steps that cannot be done where you stand with the ship and skills you have: [(activity name, 'when you are in X: reason')].
    They are not offered as the next step (no detours for a test); they are done when your route passes that place."""
    out = []
    try:
        from . import combatprep
        from .catalog import SKIP_IDS, status
        from .dailygoals import usable_blueprint
        owned = combatprep.state(con, p)["ships"]
        here = p.current_system
        hull = p.ship_name or ""
        for a in status(con, float(p.wallet_isk or 0), hull, [n for n, _s in owned]):
            if not a["unlocked"] or a["state"] == "MODELED" or (a["id"] in SKIP_IDS and a["id"] != "mining_belt") or a.get("blocked") or a["id"] == "agent_career":
                continue
            nh = a.get("needs_hull")
            if nh and not any(w.lower() in hull.lower() for w in nh):
                spots = sorted({g.name[s_] for n_, s_ in owned if any(w.lower() in n_.lower() for w in nh) and s_ in g.name})
                if spots and here not in spots:
                    out.append((a["name"], f"when you are in {spots[0]}: your {next(n_ for n_, s_ in owned if g.name.get(s_) == spots[0] and any(w.lower() in n_.lower() for w in nh))} is there"))
                continue
            if a.get("needs_bp"):
                ok_, why_ = usable_blueprint(con, p)
                if not ok_:
                    import re
                    m_ = re.search(r"your blueprint is in (\S+),", why_ or "")
                    if m_:
                        out.append((a["name"], f"when you are in {m_.group(1)}: your blueprint is there"))
                continue
            if a.get("where") and str(a["where"]).lower() != str(here).lower():
                out.append((a["name"], f"when you are in {a['where']}"))
    except Exception:                                                   # noqa: BLE001
        pass
    return out


def analyse(con, g, p, cands, horizon=HORIZON_H):
    """-> {"base": rate, "now": [...], "unlocks": [...], "enabler": step or None, "unmodeled": [...]}"""
    base = base_rate(cands)
    ranked = [c for c in cands if c[0] != float("inf")]
    model_turn = [c for c in cands if c[0] == float("inf")][:1]            # a model-building turn really is the first step when it is offered
    seq = (model_turn + ranked)[:3]
    unl = [u for u in unlock_options(con, g, p, base, horizon) if u["gain"] >= MIN_GAIN]
    enabler = next((u for u in unl if u["enabler"]), None)
    unmodeled = [a["name"] for a in status(con, float(p.wallet_isk or 0)) if a["unlocked"] and a["state"] != "MODELED" and a["id"] != "agent_career"]
    return {"base": base, "seq": seq, "unlocks": unl[:3], "enabler": enabler, "unmodeled": unmodeled, "horizon": horizon, "deferred": deferred_modeling(con, g, p)}


def enabler_step(u, base):
    st = u["enabler"]
    return (f"STEP: QUEUE A SKILL (takes 30 seconds, free)\n   QUEUE {st['skill']} {st['level']} ({st['minutes'] / 60:.1f} h of training): it leads to {u['name']}\n"
            f"   that unlock is worth about {u['gain']:,.0f} ISK more over the next {HORIZON_H:.0f} h than staying on your base rate "
            f"({u['rate']:,.0f} ISK/hr {u['src']} vs {base:,.0f} now)")


def format_long_view(an):
    L = [f"THE LONG VIEW (next {an['horizon']:.0f} active hours; every option modeled each time; base rate {an['base']:,.0f} ISK/hr)"]
    for i, c in enumerate(an["seq"]):
        L.append(f"   {'NOW   ' if i == 0 else 'THEN  '} {c[1]:<34} " + ("   model-building turn" if c[0] == float("inf") else f"{c[0]:>12,.0f} ISK/hr") + f"   ({c[3]})")
    for u in an["unlocks"]:
        wait = (f"{u['train_h']:.1f} h of training" if u["train_h"] else "") + (f"{' + ' if u['train_h'] else ''}{u['gap']:,.0f} ISK to earn" if u["gap"] else "")
        L.append(f"   UNLOCK {u['name']:<34} ~{u['rate']:>10,.0f} ISK/hr ({u['src']}), ready in {u['delay_h']:.1f} h" + (f" ({wait})" if wait else "")
                 + f"  => +{u['gain']:,.0f} ISK over the horizon")
        for part in u.get("parts", []):
            L.append(f"          {part}")
        if u["book_note"]:
            L.append(f"          books: {u['book_note']}")
    if an["unmodeled"]:
        L.append(f"   LEARN  unmodeled and unlocked: {', '.join(an['unmodeled'][:4])}" + (f" +{len(an['unmodeled']) - 4} more" if len(an["unmodeled"]) > 4 else "")
                 + "  (they compete in the same ranking: each one rises or falls with its expected ISK/hr)")
    for name, why in an.get("deferred", [])[:6]:
        L.append(f"   LATER  test {name}: {why}  (a modeling test is done when your route passes there, not as a detour)")
    return "\n".join(L)
