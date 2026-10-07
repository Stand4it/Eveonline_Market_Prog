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
STEPS = [
    ("Agent L1 step 3 Entrepreneur tritanium",
     "Beradaillot Audates (Industrialist - Entrepreneur) step 3: 333 Tritanium hand-in -> 212k bonus (DONE 05:45, paid 188,680 net)",
     []),
    ("Agent L1 step 5 Industrialist courier",
     "Arnelin Ygegnere (Industrialist - Producer) step 5: courier the Crates of Electronic Parts (40 m3) to Repute IV - AIR Laboratories (4 jumps) -> Expanded Cargohold I + 224k bonus (net ~199k); check whether you must fly back",
     []),
    ("Agent L1 step 5 Entrepreneur courier",
     "Beradaillot Audates (Industrialist - Entrepreneur) step 5: courier the Encoded Data Chip (0.1 m3) to Repute IV - AIR Laboratories (4 jumps, SAME place as Arnelin's courier) -> Expanded Cargohold I + 185k bonus (net ~165k); accept it TOGETHER with Arnelin's courier and make one trip",
     []),
    ("Agent L1 step 3 Soldier of Fortune warp disruptor",
     "Arabeton Spilmottin (Soldier of Fortune) step 3: find the fleeing pirate, fit/use the granted Civilian Warp Disruptor on him (kill the escorts, NOT the primary target) -> 96k + 107k bonus (~203k, untaxed so far)",
     []),
    ("Agent L1 step 3 Explorer data site",
     "Rounaminck Folle (Explorer) step 3 of 5 'Data Site Scanning': with the Civilian Data Analyzer fitted (Beradaillot's mission grants it) and Core Scanner Probes, scan down the Data site, hack the container, bring back the Proof of Discovery: Data -> 103k + 111k bonus (net ~190k)",
     []),
]
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
        return d if isinstance(d.get("done"), list) else {"done": []}
    except (OSError, ValueError):
        return {"done": []}


def save(s):
    STATE.write_text(json.dumps(s), encoding="utf-8")


DB = "E:/EveProfit/eve_profit_dahl.db"


def logged_done(since):
    """Missions whose timer was stopped (= a row in the activity log with that exact name) after the list was last reset."""
    import sqlite3
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        names = {r[0] for r in con.execute("SELECT activity FROM activity_log WHERE ts > ?", (since,))}
        con.close()
    except sqlite3.Error:
        return []
    return [n for n, (act, _, _) in enumerate(STEPS, 1) if act in names]


def show_list(done):
    print(f"{B}Level 1 agent missions:{X}")
    for n, (act, text, _) in enumerate(STEPS, 1):
        mark = f"{G}[x]{X}" if n in done else "[ ]"
        print(f" {mark} {n}. {text}")


def show_next(done):
    todo = [n for n in range(1, len(STEPS) + 1) if n not in done]
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
    for s in subs:
        print(f"{D}   also time the buy/sell part:  python -m eve_profit start --activity \"{s}\"   ...   python -m eve_profit stop{X}")
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
    done = sorted((set(s["done"]) | set(logged_done(s["since"]))) - set(s["ignore"]))
    if cmd == "reset":
        save({"done": [], "since": time.time()})
        done = []
        print(f"{Y}all ticks cleared{X}\n")
    elif cmd in ("back", "undo"):                               # un-tick the most recent mission, even one that was ticked from the timer log
        if done:
            n = done.pop()
            s["done"] = [x for x in s["done"] if x != n]
            s["ignore"] = sorted(set(s["ignore"]) | {n})
            save(s)
            print(f"{Y}went back: mission {n} is open again{X}\n")
        else:
            print(f"{Y}nothing to go back to{X}\n")
    elif cmd == "skip":                                         # tick off the current mission with no timer (already done, or timed by hand)
        todo = [n for n in range(1, len(STEPS) + 1) if n not in done]
        if todo:
            n = todo[0]
            s["done"] = sorted(set(s["done"]) | {n})
            s["ignore"] = [x for x in s["ignore"] if x != n]
            save(s)
            done = sorted(set(done) | {n})
            print(f"{Y}skipped mission {n}{X}\n")
    elif cmd == "done":
        todo = [n for n in range(1, len(STEPS) + 1) if n not in done]
        n = int(sys.argv[2]) if len(sys.argv) > 2 else (todo[0] if todo else None)
        if n and n not in done and 1 <= n <= len(STEPS):
            done.append(n)
            save(s)
            print(f"{Y}ticked off mission {n}{X}\n")
    elif cmd == "list":
        show_list(done)
        return
    show_next(done)


if __name__ == "__main__":
    main()
