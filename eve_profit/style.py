"""Terminal color that works for EVERY kind of color vision: the task you must do is marked by BRIGHTNESS and SHAPE (a white-on-blue banner,
bold text, '>>' markers), never by hue alone; the background chatter (progress, logs) is dimmed grey. With no color at all (piped output,
NO_COLOR=1, EVE_COLOR=0) the same markers and labels still appear, so nothing depends on seeing a color.
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
    return _w("90", s)                                                  # grey: background chatter


def bold(s):
    return _w("1", s)


def accent(s):
    return _w("1;93", s)                                                # bold bright yellow: high luminance, stays visible for red/green and blue/yellow color blindness


def banner(label, width=70):
    text = f" >> {label} << "
    return _w("1;97;44", text.ljust(width))                             # bold white on blue: contrast by brightness, not by hue


def task_block(text, label="YOUR TASK - do this one thing now"):
    """The step text with a banner above it, its first line in bold yellow and the 'When done' footer dimmed."""
    lines = text.split("\n")
    out = [banner(label)]
    first = True
    for ln in lines:
        s = ln.strip()
        if first and s:
            out.append(accent(ln))
            first = False
        elif s.startswith(("Time it:", "In game:")):
            out.append(bold(ln))
        elif s.startswith(("When done:", "(look ahead", "(everything", "(more detail")):
            out.append(dim(ln))
        else:
            out.append(ln)
    return "\n".join(out)
