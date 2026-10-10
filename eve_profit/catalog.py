"""The activity map (activity_catalog.json): everything a player can do, what unlocks it, prior ISK/hr, and how much of it your own timed runs
have MODELED. Drives `models` and the exploration turns in `next` (an unmodeled, unlocked option is offered every 4th step and the moment it
unlocks), so the model keeps growing until every option is known and the best ISK/hr is always on the next step."""
import json
import os

MODELED_RUNS = 3
EVERY = 4            # every 4th recommendation is a model-building turn when something unmodeled is unlocked
_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "activity_catalog.json")


def load():
    try:
        return json.load(open(_FILE, encoding="utf-8")).get("activities", [])
    except (OSError, ValueError):
        return []


def skill_levels(con):
    """{skill name lower: level} for the trained skills (queue levels not counted)."""
    try:
        return {r[0].lower(): r[1] for r in con.execute(
            "SELECT t.name, s.level FROM character_skills s JOIN types t ON t.type_id=s.skill_id")}
    except Exception:                                                   # noqa: BLE001
        return {}


def missing_for(act, levels, wallet):
    miss = [f"{k} {v}" for k, v in act.get("requires", {}).items() if levels.get(k.lower(), 0) < v]
    if act.get("isk_min") and wallet < act["isk_min"]:
        miss.append(f"{act['isk_min']:,.0f} ISK")
    return miss


def runs_for(con, act):
    """(runs, ISK/hr or None) from the activity_log names that contain one of the activity's match words."""
    try:
        rows = con.execute("SELECT activity,isk,hours FROM activity_log WHERE hours>0").fetchall()
    except Exception:                                                   # noqa: BLE001
        return 0, None
    hit = [r for r in rows if any(m in r["activity"].lower() for m in act.get("match", []))]
    h = sum(r["hours"] for r in hit)
    return len(hit), (sum(r["isk"] for r in hit) / h if h else None)


def status(con, wallet=0.0):
    levels = skill_levels(con)
    out = []
    for a in load():
        n, rate = runs_for(con, a)
        miss = missing_for(a, levels, wallet)
        out.append({**a, "runs": n, "rate": rate, "missing": miss, "unlocked": not miss,
                    "state": "MODELED" if n >= MODELED_RUNS else ("PARTIAL" if n else "UNMODELED")})
    return out


def voi(a, best_known):
    """Value of information: how much better than your best known rate this option could be, shrinking as you time it."""
    hi = a["prior"][1]
    return max(hi - best_known, 0.2 * hi) / (1.0 + a["runs"])          # priors are guesses: an untimed option always keeps some pull


def models_report(con, wallet=0.0):
    st = status(con, wallet)
    L = [f"{'activity':<46} {'area':<12} {'runs':>4} {'ISK/hr':>11}  {'prior ISK/hr':<19} state"]
    for a in sorted(st, key=lambda x: (x["area"], x["name"])):
        pr = f"{a['prior'][0] / 1000:,.0f}k - {a['prior'][1] / 1000:,.0f}k"
        rate = f"{a['rate']:,.0f}" if a["rate"] else "-"
        state = a["state"] + ("" if a["unlocked"] else "  LOCKED: needs " + ", ".join(a["missing"]))
        L.append(f"{a['name'][:46]:<46} {a['area']:<12} {a['runs']:>4} {rate:>11}  {pr:<19} {state}")
    ok = [a for a in st if a["unlocked"]]
    done = [a for a in ok if a["state"] == "MODELED"]
    L += ["", f"MODEL MAP: {len(done)} of {len(ok)} unlocked activities are modeled ({MODELED_RUNS}+ timed runs); {len(st) - len(ok)} more are locked behind skills or ISK.",
          "Unmodeled options are offered by `next` every 4th step and the moment they unlock; new game features: add them to activity_catalog.json."]
    return "\n".join(L)


def pick_experiment(con, wallet, best_known_rate, counter, last_exp, seen):
    """Which unmodeled, unlocked activity should be offered now? -> (activity or None, reason, new_seen_ids)
    NEW unlock => immediately; otherwise every EVERY-th step the highest value-of-information one."""
    st = status(con, wallet)
    unlocked = [a for a in st if a["unlocked"]]
    new_ids = [a["id"] for a in unlocked if a["id"] not in seen]
    unmodeled = [a for a in unlocked if a["state"] != "MODELED" and a["id"] != "agent_career"]
    fresh = [a for a in unmodeled if a["id"] in new_ids and seen]        # first call just records what is already unlocked
    if fresh:
        a = max(fresh, key=lambda x: voi(x, best_known_rate))
        return a, "NEW: just unlocked, never timed", new_ids
    if unmodeled and counter - last_exp >= EVERY:
        a = max(unmodeled, key=lambda x: voi(x, best_known_rate))
        if voi(a, best_known_rate) > 0:
            return a, f"model-building turn (every {EVERY}th step): it could beat your {best_known_rate:,.0f} ISK/hr", new_ids
    return None, "", new_ids


def experiment_step(a, reason):
    lo, hi = a["prior"]
    return (f"STEP: TEST {a['name']} ({reason})\n   {a['how']}\n   about {a['minutes']} min. Unmodeled: it could pay {lo:,.0f} - {hi:,.0f} ISK/hr; "
            f"{MODELED_RUNS} timed runs turn the guess into your own number.")
