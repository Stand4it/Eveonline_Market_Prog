"""Terminal color that works for EVERY kind of color vision: what to DO (the task line, what to sell and the sell-or-refine verdict) is bright yellow on black,
the commands to start and stop are bold white, everything else is plain. With no color at all (piped output, NO_COLOR=1, EVE_COLOR=0) the '>> '
marker still appears, so nothing depends on seeing a color.
EVE_COLOR=1 forces color on; the default is on only when the output is a real terminal."""
import os
import sys

_ON = None
RESET = "\x1b[0m"


def enabled():
    global _ON
    if _ON is not None:
        return _ON
    env = os.environ
    if env.get("NO_COLOR") or env.get("EVE_COLOR") == "0":
        _ON = False
    elif env.get("EVE_COLOR") == "1" or env.get("FORCE_COLOR"):
        _ON = True
    else:
        try:
            _ON = bool(sys.__stdout__.isatty())
        except Exception:                                               # noqa: BLE001
            _ON = False
    if _ON and os.name == "nt":                                         # old Windows consoles need ANSI switched on
        try:
            import ctypes
            k = ctypes.windll.kernel32
            h = k.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            if k.GetConsoleMode(h, ctypes.byref(mode)):
                k.SetConsoleMode(h, mode.value | 0x0004)
        except Exception:                                               # noqa: BLE001
            pass
    return _ON


def _w(code, s):
    return f"\x1b[{code}m{s}{RESET}" if enabled() and s else s


def dim(s):
    return s                                                            # other text stays plain white (user's choice): no dimming


def bold(s):
    return _w("1", s)


import re

HUE = "1;93;40"                       # bold bright yellow text on a black background
CMD = re.compile(r'python -m eve_profit \w+(?: --[\w-]+(?: "[^"]*"| (?!--)[^\s)]+)?)*')


def hue(s):
    """Yellow on black: the lines that say WHAT to do (the task, what to sell/buy, where to sell)."""
    return _w(HUE, s)


def white_cmds(line):
    """Every 'python -m eve_profit ...' command in the line in bold white, so the commands to start and stop are easy to find."""
    return CMD.sub(lambda m: _w("1;97", m.group(0)), line) if enabled() else line


def task_block(text):
    """The step text: headline (marked '>> '), the item lines ('66,666 x Scordite'), the sell / buy / keep lines on the way and the refine-or-sell verdict ('=> SELL RAW') in yellow on black;
    the start / stop / sync / next commands in bold white; everything else plain."""
    out, first = [], True
    for ln in text.split("\n"):
        s = ln.strip()
        if first and s:
            out.append(hue(">> " + s))
            first = False
        elif re.match(r"^\s+[\d,]+ x ", ln) or re.match(r"^\s+(sell|buy|keep) ", ln) or s.startswith(("=> SELL RAW", "=> REFINE FIRST")):
            out.append(hue(ln))
        elif s.startswith(("Time it:", "When done:")):
            out.append(white_cmds(ln))
        else:
            out.append(ln)
    return "\n".join(out)
