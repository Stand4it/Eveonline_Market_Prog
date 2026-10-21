"""Where does `next` spend its time? Runs `python -m eve_profit <args>` under cProfile and prints the slowest functions.
python scripts/profile_next.py [next args...]      (stats saved to data/profile_next.prof; reprint: python scripts/profile_next.py --show)"""
import cProfile
import os
import pstats
import runpy
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "profile_next.prof")


def show(n=35):
    s = pstats.Stats(OUT)
    s.sort_stats("cumulative").print_stats(r"eve_profit", n)
    s.sort_stats("tottime").print_stats(15)


if "--show" not in sys.argv:
    os.chdir(ROOT)
    sys.path.insert(0, ROOT)
    sys.argv = ["eve_profit"] + (sys.argv[1:] or ["next"])
    prof = cProfile.Profile()
    try:
        prof.runcall(runpy.run_module, "eve_profit", run_name="__main__")
    except SystemExit:
        pass
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    prof.dump_stats(OUT)
show()
