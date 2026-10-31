"""Where is a slow `next` right now? Runs `python -m eve_profit <args>` and writes every thread's stack to data/stack_next.txt
every N seconds (no profiler overhead, so timings stay real). Summarise: python scripts/stack_next.py --show
python scripts/stack_next.py [--every 30] [next args...]"""
import collections
import faulthandler
import os
import re
import runpy
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "stack_next.txt")


def show():
    """The eve_profit line each sample was in (innermost), most frequent first."""
    text = open(OUT, encoding="utf-8", errors="replace").read()
    hits = collections.Counter()
    for block in text.split("Thread 0x"):
        frames = re.findall(r'File "([^"]*eve_profit[^"]*)", line (\d+) in (\w+)', block)
        if frames and "Heartbeat" not in block and "pretty.py" not in frames[0][0]:
            f, ln, fn = frames[0]                                       # faulthandler prints innermost first
            hits[f"{os.path.basename(f)}:{ln} {fn}"] += 1
    for k, n in hits.most_common(25):
        print(f"{n:4}  {k}")


if "--show" in sys.argv:
    show()
    sys.exit()
args = sys.argv[1:]
every = 30
if "--every" in args:
    i = args.index("--every")
    every = int(args[i + 1])
    del args[i:i + 2]
os.chdir(ROOT)
sys.path.insert(0, ROOT)
os.makedirs(os.path.dirname(OUT), exist_ok=True)
fh = open(OUT, "w", encoding="utf-8")
faulthandler.dump_traceback_later(every, repeat=True, file=fh)
sys.argv = ["eve_profit"] + (args or ["next"])
try:
    runpy.run_module("eve_profit", run_name="__main__")
finally:
    faulthandler.cancel_dump_traceback_later()
    fh.close()
    show()
