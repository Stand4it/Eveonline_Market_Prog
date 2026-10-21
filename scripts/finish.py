"""Finish a change in one call: refresh docs, run tests, add a DECISIONS line, commit and push.
python scripts/finish.py "<commit subject>" ["<DECISIONS.md line>"]
Prints only: docs result, test summary, push result."""
import os
import subprocess
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GIT_SAVE = r"C:\Users\Martin Dahl\OneDrive\Documents\git_save.py"


def run(args):
    r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return (r.stdout or "") + (r.stderr or "")


def finish(subject, decision=None):
    if decision:
        with open(os.path.join(ROOT, "md", "DECISIONS.md"), "a", encoding="utf-8", newline="\n") as f:
            f.write(f"- {date.today()} {decision}\n")
    docs = run([sys.executable, "-m", "eve_profit", "docs"])
    print("docs:", "ok" if "Wrote md/STATE.md" in docs else "FAILED\n" + docs[-800:])
    tests = run([sys.executable, "-m", "pytest", "-q"]).strip().splitlines()
    print("tests:", tests[-1] if tests else "no output")
    print(run([sys.executable, GIT_SAVE, ROOT, subject]).strip())


if __name__ == "__main__":
    finish(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
