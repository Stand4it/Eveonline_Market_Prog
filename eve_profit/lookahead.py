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


def unlock_options(con, g, p, base, horizon=HORIZON_H):
    """Every locked, routable activity as a chain: train skills -> (books) -> (ISK gap) -> its own rate. Best gain first."""
    try:
        from .advisor import virtual_levels
        from .trainplan import book_list, plan_training, trainable_now
    except Exception:                                                   # noqa: BLE001
        return []
    wallet = float(p.wallet_isk or 0.0)
    out = []
    for a in status(con, wallet):
        if a["unlocked"] or a.get("blocked"):
            continue
        trained = skill_levels(con)
        goals, queue_h = [], 0.0
        try:
            vlv = {r[0].lower(): r[1] for r in con.execute("SELECT t.name, v.level FROM types t JOIN (SELECT skill_id, level FROM character_skills) v ON v.skill_id=t.type_id")}
            for r in con.execute("SELECT t.name, q.level FROM skill_queue q JOIN types t ON t.type_id=q.skill_id"):
                vlv[r[0].lower()] = max(vlv.get(r[0].lower(), 0), r[1])
        except Exception:                                               # noqa: BLE001
            vlv = trained
        for sk, lvl in a.get("requires", {}).items():
            if trained.get(sk.lower(), 0) >= lvl:
                continue
            if vlv.get(sk.lower(), 0) >= lvl:
                queue_h = max(queue_h, _queue_hours(con, sk))          # already queued: just wait for it
            else:
                goals.append((sk, lvl, f"unlocks {a['name']}"))
        train_h, books_cost, enabler, book_note = queue_h, 0.0, None, ""
        if goals:
            try:
                res = plan_training(con, 24 * 365, goals)
            except Exception:                                           # noqa: BLE001
                continue
            if res["unknown"] or not res["steps"]:
                continue
            train_h = max(train_h, res["steps"][-1]["cum"] / 60.0)
            try:
                books = book_list(con, g, p, res, hours=24 * 365)
            except Exception:                                           # noqa: BLE001
                books = []
            for name, price, where, jumps in books:
                if price is None:
                    book_note = f"{name} book: no seller found nearby"
                else:
                    books_cost += price
                    book_note += f"{name} book ~{price:,.0f} at {where} ({jumps} jumps); "
            now = trainable_now(con, res)
            if now:
                enabler = now[0]
        gap = max(0.0, float(a.get("isk_min", 0) or 0) - wallet)
        rate_u, src = act_rate(a)
        delay_h = max(train_h, gap / max(base, 1.0))
        gain = chain_gain(base, rate_u, delay_h, horizon, books_cost)
        out.append({"id": a["id"], "name": a["name"], "rate": rate_u, "src": src, "delay_h": delay_h, "train_h": train_h, "gap": gap,
                    "books_cost": books_cost, "book_note": book_note.strip("; "), "gain": gain, "enabler": enabler})
    out.sort(key=lambda o: -o["gain"])
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
    return {"base": base, "seq": seq, "unlocks": unl[:3], "enabler": enabler, "unmodeled": unmodeled, "horizon": horizon}


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
        if u["book_note"]:
            L.append(f"          books: {u['book_note']}")
    if an["unmodeled"]:
        L.append(f"   LEARN  unmodeled and unlocked: {', '.join(an['unmodeled'][:4])}" + (f" +{len(an['unmodeled']) - 4} more" if len(an["unmodeled"]) > 4 else "")
                 + "  (a model-building turn comes every 4th timer)")
    return "\n".join(L)
