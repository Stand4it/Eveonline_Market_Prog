"""Mining as ONE step at a time: accept the freelance mining jobs (one step each, up to 3), fly to the mining system (one hop per step, destination set),
undock and warp to a belt, and only then the mining step itself. Wraps the mining step that `next` has chosen."""
import json
import os

_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "freelance_jobs.json")
SHOWN = "job_shown"
MAX_ACCEPTED = 3


def _jobs():
    try:
        return json.load(open(_FILE, encoding="utf-8")).get("mining_jobs", [])
    except (OSError, ValueError):
        return []


def is_mining_step(text):
    first = (text or "").split("\n", 1)[0].lower()
    return first.startswith(("step: test freelance belt mining", "step: mine"))


def prestep(con, g, p, text):
    """The step to show instead of the mining step while there is something to do first. -> text (unchanged when the mining itself is next)."""
    if not is_mining_step(text):
        return text
    from .mining import accepted_jobs
    from .listings import is_gone, key_of
    jobs, acc = [j for j in _jobs() if not is_gone(con, "freelance", key_of(j.get("title", ""), "mine"))], accepted_jobs(con)   # a withdrawn / finished job is not offered
    n_acc = sum(1 for j in jobs if j["ore"] in acc)
    todo = [j for j in jobs if j["ore"] not in acc]
    if todo and n_acc < MAX_ACCEPTED:
        j = todo[0]
        try:
            con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (SHOWN, j["ore"]))
            con.commit()
        except Exception:                                               # noqa: BLE001
            pass
        return "\n".join([f"STEP: ACCEPT FREELANCE JOB {n_acc + 1} of {MAX_ACCEPTED} - Mine {j['ore']} (about 1 minute)",
                          f"   DO ONLY THIS: Neocom > Freelance Jobs > find '{j.get('title', 'Mine ' + j['ore'])}' > click it > Accept.",
                          f"   It pays {j['isk_per_unit']:.2f} ISK per unit mined" + (" (assumed: check the detail page)" if j.get("unverified") else "") + "; you keep the ore. No cost, no risk.",
                          "   When it is accepted run:  python -m eve_profit done"])
    try:
        from .mining_sites import rank_sites
        site = rank_sites(con)[0]
        here = p.current_system
        if site["system"] != here:
            r = g.route(g.id_of(here), g.id_of(site["system"]), 60, p.avoid_yellow)
            hop = g.name[r.path[1]] if len(r.path) > 1 else site["system"]
            return "\n".join([f"STEP: FLY to {hop}",
                              f"   DO ONLY THIS: fly to {hop} and stop there. Then run  python -m eve_profit next  (it plans again from there).",
                              f"   LATER: mine {site['best_ore'] or 'ore'} at {site['system']} ({r.jumps} jumps from here, {site['belts']} belts)"])
        if getattr(p, "current_location_id", 0):                       # docked in the mining system
            return "\n".join([f"STEP: UNDOCK and warp to an asteroid belt in {here} (about 2 minutes)",
                              "   DO ONLY THIS: undock, open the Overview, find an Asteroid Belt, right-click > Warp to Within 0 m. Then run  python -m eve_profit next."])
    except Exception:                                                   # noqa: BLE001
        pass
    return text


def job_done(con):
    """`done`: the job that was shown is accepted. -> message or None."""
    try:
        r = con.execute("SELECT value FROM meta WHERE key=?", (SHOWN,)).fetchone()
    except Exception:                                                   # noqa: BLE001
        return None
    if not r:
        return None
    from .mining import accept_job
    con.execute("DELETE FROM meta WHERE key=?", (SHOWN,))
    con.commit()
    return accept_job(r[0], con)
