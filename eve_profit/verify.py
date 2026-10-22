"""Every BUY or SELL step ends with the command that double-checks it (owner 2026-10-21): scripts/where_buy.py / where_sell.py list every market that
buys cheaper or pays more, priced with your time, so a wrong step (a bug, stale prices) shows at a glance."""
import re

_ITEM = re.compile(r"(?:^|\s)(?:buy |sell )?([\d,]+) x ([A-Za-z0-9][\w'\-:. ]*?[\w)'])(?=\s{2,}|\s+@|\s+at |\s+~|\s*\(|\s*$|:)")
MAX_LINES = 3


def check_lines(step):
    """-> lines with the check command(s) for the items of a BUY / SELL / LIST step, [] for any other step."""
    first = (step or "").split("\n", 1)[0].upper()
    if first.startswith(("STEP: BUY", "STEP: FIT", "STEP: ACQUIRE")) or " BUY " in first:
        script = "where_buy.py"
    elif first.startswith(("STEP: SELL", "STEP: LIST")):
        script = "where_sell.py"
    else:
        return []
    seen, out = set(), []
    lines = step.split("\n")
    title = re.split(r" - (?:BUY|BUILD|MAKE)\b", lines[0].split(":", 1)[-1])[0]                  # ACQUIRE names the item in its title
    for ln in ([title] if first.startswith("STEP: ACQUIRE") else []) + lines[1:]:
        if "python -m" in ln or "LATER:" in ln or "keep " in ln.lower():
            continue
        for m in _ITEM.finditer(ln):
            qty, name = int(m.group(1).replace(",", "")), m.group(2).strip()
            if name.lower() in seen or name[0].isdigit():
                continue
            seen.add(name.lower())
            out.append(f"   CHECK (every market that {'sells cheaper' if script == 'where_buy.py' else 'pays more'}, priced with your time):  "
                       f"python scripts/{script} \"{name}\" {qty}")
            if len(out) >= MAX_LINES:
                return out
    return out


def add(step):
    lines = check_lines(step)
    return step + ("\n" + "\n".join(lines) if lines else "")
