"""Progress and model value in ISK-equivalent (progress_values.json): lets `next` weigh character progression and learning for the model
against plain ISK. A mission advances its agent chain and standing (agent_step); a run in a career with fewer than 3 timed runs teaches the
model (new_career_run each). Never-timed activities get a prior ISK/hr until real runs replace it."""
import json
import os

from .careers import MIN_RUNS, career_of_activity

_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "progress_values.json")
DEFAULTS = {"agent_step": 30000.0, "new_career_run": 60000.0, "career_runs_until_measured": MIN_RUNS,
            "priors_isk_hr": {"Project Discovery": 120000.0, "Mining": 150000.0}, "prior_minutes": {"Project Discovery": 30, "Mining": 45}}


def values():
    try:
        return {**DEFAULTS, **json.load(open(_FILE, encoding="utf-8"))}
    except (OSError, ValueError):
        return dict(DEFAULTS)


def run_counts(con):
    out = {}
    try:
        for (n,) in con.execute("SELECT activity FROM activity_log WHERE hours>0"):
            c = career_of_activity(n)
            out[c] = out.get(c, 0) + 1
    except Exception:                                                   # noqa: BLE001
        pass
    return out


def progress_isk(career, counts, v=None, is_agent=True):
    """ISK-equivalent a run of this career adds: chain/standing progress (agents) + model learning while it has < N timed runs."""
    v = v or values()
    total = v["agent_step"] if is_agent else 0.0
    if counts.get(career, 0) < v["career_runs_until_measured"]:
        total += v["new_career_run"]
    return total


def experiment_candidates(con, counts=None, v=None):
    """Careers with NO timed run yet and no agent mission needed (Project Discovery, mining): [(ISK/hr incl. model value, label, step text)]."""
    v, counts = v or values(), counts or run_counts(con)
    out = []
    for career, prior in v["priors_isk_hr"].items():
        if counts.get(career, 0) >= v["career_runs_until_measured"]:
            continue
        mins = float(v["prior_minutes"].get(career, 30))
        rate = (prior * mins / 60.0 + progress_isk(career, counts, v, is_agent=False)) * 60.0 / mins
        if career == "Project Discovery":
            text = ("STEP: TEST Project Discovery (zero risk, works while docked)\n"
                    "   Neocom > Business > Project Discovery: classify cell images for about 30 minutes.\n"
                    f"   unmeasured: a guess of {prior:,.0f} ISK/hr until you have {v['career_runs_until_measured']} timed runs; it teaches the model")
        else:
            text = ("STEP: TEST freelance mining (Venture in the belt)\n"
                    "   Mine about 45 minutes, dock, unload the ore into the hangar, then stop the timer.\n"
                    f"   unmeasured: a guess of {prior:,.0f} ISK/hr until you have {v['career_runs_until_measured']} timed runs; it teaches the model")
        out.append((rate, f"test {career}", text))
    return out
