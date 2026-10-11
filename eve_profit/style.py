"""Terminal color that works for EVERY kind of color vision: the task you must do is ONE line, black on bright yellow (brightness contrast, not hue),
marked with '>> '; all other text stays plain white. With no color at all (piped output, NO_COLOR=1, EVE_COLOR=0) the '>> ' marker still appears,
so nothing depends on seeing a color.
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


def highlight(s, width=70):
    """The task line: black on bright yellow (maximum brightness contrast for every kind of color vision), padded into a bar."""
    return _w("30;103", s.ljust(width))


def task_block(text):
    """The step text with its headline marked '>> ' and highlighted black on yellow; every other line stays plain."""
    out, first = [], True
    for ln in text.split("\n"):
        if first and ln.strip():
            out.append(highlight(">> " + ln.strip()))
            first = False
        else:
            out.append(ln)
    return "\n".join(out)
