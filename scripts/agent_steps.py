"""Level 1 agent checklist.  It only LISTS what to do next - it never starts or stops a timer.

    python scripts/agent_steps.py            # same as next: shows the next mission + the exact START / STOP commands (START is copied to your clipboard)
    python scripts/agent_steps.py next       # same
    python scripts/agent_steps.py list       # every mission and whether it is done
    python scripts/agent_steps.py done       # tick off the current mission (no timers), then show the next one
    python scripts/agent_steps.py done 3     # tick off mission 3 instead
    python scripts/agent_steps.py skip       # mistake? jump past the current mission (no timers)
    python scripts/agent_steps.py back       # mistake? re-open the last mission that was ticked off (no timers)
    python scripts/agent_steps.py reset      # clear all ticks

Timing is done by you with the normal commands, for EVERYTHING you do (missions, buys, sells, hauls) so the measured ISK/hr stays current:
    python -m eve_profit start --activity "NAME"        ...do it...        python -m eve_profit stop
State: scripts/agent_steps_state.json  ({"done": [mission numbers]}).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

STATE = Path(__file__).with_name("agent_steps_state.json")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
DB = "E:/EveProfit/eve_profit_dahl.db"


def build_steps():
    """The checklist is built from agent_offers.json (open offers only, best ISK/hr first), so it never goes stale.
    -> [(timer name, text, [])]. The timer name is the offer's `timer_name`."""
    try:
        import sqlite3
        from eve_profit.nextstep import offers_rows
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        rows = offers_rows(con)
        con.close()
    except Exception:                                           # noqa: BLE001 - no DB / old code: fall back to file order
        import json
        rows = []
        try:
            for o in json.loads((Path(__file__).resolve().parents[1] / "agent_offers.json").read_text(encoding="utf-8"))["offers"]:
                if o.get("available", True):
                    rows.append((0, 0, 0, o, []))
        except (OSError, ValueError):
            pass
    out = []
    for rate, net, minutes, o, tags in rows:
        name = o.get("timer_name") or ("Agent L1 " + o["agent"].split(" (")[0])
        out.append((name, f"{o['agent']} {o['mission']}  [~{net:,.0f} ISK net, ~{minutes:.0f} min, ~{rate:,.0f} ISK/hr]", []))
    return out


STEPS = build_steps()
os.system("")                                                   # switches on ANSI colours in the Windows console
G, Y, C, B, D, X = "\033[92m", "\033[93m", "\033[96m", "\033[1m", "\033[2m", "\033[0m"


def clip(text):
    try:                                                        # fire-and-forget: a stuck clipboard call can never freeze the script
        p = subprocess.Popen(["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value $env:CLIP_TEXT"],
                             env=dict(os.environ, CLIP_TEXT=text), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            return p.wait(timeout=8) == 0
        except subprocess.TimeoutExpired:
            p.kill()
            return False
    except OSError:
        return False


def load():
    try:
        d = json.loads(STATE.read_text(encoding="utf-8"))
        if not isinstance(d.get("done"), list):
            return {"done": []}
        d["done"] = [x for x in d["done"] if isinstance(x, str)]        # older versions stored mission numbers: those no longer apply
        d["ignore"] = [x for x in d.get("ignore", []) if isinstance(x, str)]
        return d
    except (OSError, ValueError):
        return {"done": []}


def save(s):
    STATE.write_text(json.dumps(s), encoding="utf-8")


DB = "E:/EveProfit/eve_profit_dahl.db"


def logged_done(since):
    """Timer names that were stopped (= a row in the activity log with that exact name) after the list was last reset."""
    import sqlite3
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        names = {r[0] for r in con.execute("SELECT activity FROM activity_log WHERE ts > ?", (since,))}
        con.close()
    except sqlite3.Error:
        return set()
    return {act for act, _, _ in STEPS if act in names}


def todo_list(done):
    return [n for n, (act, _, _) in enumerate(STEPS, 1) if act not in done]


def show_list(done):
    print(f"{B}Level 1 agent missions (open offers, best ISK/hr first; built from agent_offers.json):{X}")
    for n, (act, text, _) in enumerate(STEPS, 1):
        mark = f"{G}[x]{X}" if act in done else "[ ]"
        print(f" {mark} {n}. {text}")


def show_next(done):
    todo = todo_list(done)
    if not todo:
        print(f"{G}{B}All listed missions are ticked off.{X} Screenshot each agent's new offer and send it to Claude to refresh this list.")
        print(f"{D}Results so far:  python -m eve_profit activities{X}")
        return
    n = todo[0]
    act, text, subs = STEPS[n - 1]
    start = f'python -m eve_profit start --activity "{act}"'
    print(f"{G}{B}NEXT MISSION ({n} of {len(STEPS)}):{X} {G}{text}{X}")
    print(f"\n{C}{B}1) START THE TIMER{X}{C} {'(copied to your clipboard - paste it)' if clip(start) else ''}{X}")
    print(f"{B}{start}{X}")
    for sub in subs:
        print(f"{D}   also time the buy/sell part:  python -m eve_profit start --activity \"{sub}\"   ...   python -m eve_profit stop{X}")
    print(f"\n{C}{B}2) DO THE MISSION, then STOP THE TIMER{X}")
    print(f"{B}python -m eve_profit stop{X}")
    print(f"\n{D}(When you stop the timer the mission is ticked off automatically - run next again to see the one after it.){X}")
    print(f"{D}Made a mistake?  skip = jump past this mission   |   back = re-open the last one   (python scripts/agent_steps.py skip / back){X}")
    print(f"\n{Y}Time every buy, sell and haul the same way (start --activity \"Buy ...\" / stop) so the planner stays current.{X}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "next"
    import time
    s = load()
    s.setdefault("since", time.time())
    s.setdefault("ignore", [])
    done = (set(s["done"]) | logged_done(s["since"])) - set(s["ignore"])
    if cmd == "reset":
        save({"done": [], "since": time.time()})
        done = set()
        print(f"{Y}all ticks cleared{X}\n")
    elif cmd in ("back", "undo"):                               # re-open the most recently ticked mission
        ticked = [act for act, _, _ in STEPS if act in done]
        if ticked:
            name = ticked[-1]
            s["done"] = [x for x in s["done"] if x != name]
            s["ignore"] = sorted(set(s["ignore"]) | {name})
            save(s)
            done.discard(name)
            print(f"{Y}went back: '{name}' is open again{X}\n")
        else:
            print(f"{Y}nothing to go back to{X}\n")
    elif cmd in ("skip", "done"):                               # tick off a mission with no timer (already done, or timed by hand)
        todo = todo_list(done)
        n = int(sys.argv[2]) if cmd == "done" and len(sys.argv) > 2 else (todo[0] if todo else None)
        if n and 1 <= n <= len(STEPS):
            name = STEPS[n - 1][0]
            s["done"] = sorted(set(s["done"]) | {name})
            s["ignore"] = [x for x in s["ignore"] if x != name]
            save(s)
            done.add(name)
            print(f"{Y}ticked off mission {n}: {name}{X}\n")
    elif cmd == "list":
        show_list(done)
        return
    show_next(done)


if __name__ == "__main__":
    main()
