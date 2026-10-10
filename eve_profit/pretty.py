"""Readability for every command: headings (lines that start with CAPITALISED words) get a blank line before and a rule
under them, so long output is easy to scan. Pure presentation; the text of each line is unchanged."""
import re
import sys

HEAD = re.compile(r"^[A-Z][A-Z0-9'/&-]{2,}( [A-Z0-9'/&-]{2,}| [a-z]{1,3}(?= [A-Z]))*(:|\s|$)")
WIDTH = 70


class Pretty:
    def __init__(self, out):
        self.out, self.buf, self.prev = out, "", ""
        self.box = 0

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            self._line(line)
        return len(s)

    def _emit(self, line):
        self.out.write(line + "\n")
        self.prev = line

    def _line(self, line):
        if line.startswith("====="):
            self._emit(line)
            return
        if len(line) <= 60 and HEAD.match(line) and not self.prev.startswith("=====") and not line.startswith(("STEP:", ">>>")):
            if self.prev.strip():
                self._emit("")
            self._emit(line)
            self._emit("-" * min(WIDTH, max(len(line), 20)))
            return
        self._emit(line)

    def flush(self):
        if self.buf:
            self._line(self.buf)
            self.buf = ""
        self.out.flush()

    def __getattr__(self, name):
        return getattr(self.out, name)


BAR = "#" * 70


class pretty_output:
    """Wrap stdout. With a title (the command name) the output is framed by bold bars and blank lines so you can see where it starts and ends."""

    def __init__(self, title=None):
        self.title = title

    def __enter__(self):
        self.old = sys.stdout
        if self.title:
            self.old.write(f"\n\n{BAR}\n{BAR}\n##  START  {self.title}\n{BAR}\n\n")
        sys.stdout = Pretty(self.old)
        return self

    def __exit__(self, *exc):
        sys.stdout.flush()
        sys.stdout = self.old
        if self.title:
            self.old.write(f"\n{BAR}\n##  END  {self.title}\n{BAR}\n{BAR}\n\n\n")
            self.old.flush()


MESSAGES = ["still working, all good", "making progress, nothing wrong", "still crunching the numbers, going well",
            "hang in there, it is moving along", "working through it, everything is fine"]


class Heartbeat:
    """Every `every` seconds a command is still running, print a short positive line so you know it has not hung."""

    def __init__(self, every=30.0, out=None):
        import threading
        self.every, self.out, self.stop_flag, self.t0 = every, out, threading.Event(), None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        import time
        n = 0
        while not self.stop_flag.wait(self.every):
            n += 1
            el = int(time.time() - self.t0)
            line = f"\n   ... {el // 60}:{el % 60:02d} elapsed - {MESSAGES[(n - 1) % len(MESSAGES)]}\n"
            (self.out or sys.stdout).write(line)
            (self.out or sys.stdout).flush()

    def __enter__(self):
        import time
        self.t0 = time.time()
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stop_flag.set()
