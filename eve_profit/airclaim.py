"""AIR Career rewards are wiped on 2026-11-10 (Fractured Skies moves the program into Achievements and resets all progress).
Until then `next` shows a step once a day to CLAIM every reward waiting in the Rewards tab; in the last 2 days it goes first.
Mark it done with:  python -m eve_profit done --goal "air claimed"  (it comes back the next day while rewards can still pile up)."""
from datetime import date

from .health import record as _hrec

RESET = date(2026, 11, 10)
KEY = "air_claim_last"
RATE = 30_000_000.0          # a 1-minute claim of ~500,000 ISK of rewards (seen 2026-10-17) is worth this per hour
URGENT_DAYS = 2


def _last(con):
    try:
        r = con.execute("SELECT value FROM meta WHERE key=?", (KEY,)).fetchone()
        return r[0] if r else ""
    except Exception as _he:                                            # noqa: BLE001
        _hrec('airclaim', _he)
        return ""


def mark(con, today=None):
    con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (KEY, str(today or date.today())))
    con.commit()
    return "OK, AIR rewards marked as claimed today. The step comes back tomorrow until the reset on 2026-11-10."


def candidate(con, today=None):
    """-> (rate, step text) or None (after the reset, or already claimed today)."""
    today = today or date.today()
    left = (RESET - today).days
    if left <= 0 or _last(con) == str(today):
        return None
    urgent = left <= URGENT_DAYS
    text = "\n".join([
        f"STEP: CLAIM YOUR AIR CAREER REWARDS - they are WIPED on {RESET} ({left} day{'s' if left != 1 else ''} left)",
        "   DO ONLY THIS (1 minute, free):",
        "      1. Neocom (left bar) > Opportunities (or press the AIR Career Program icon).",
        "      2. Click 'Your Rewards' (top left). Every reward with a Claim button: click Claim.",
        "      3. Skill points land as unallocated SP; ISK goes to your wallet; items to your hangar.",
        "   Then run:  python -m eve_profit done --goal \"air claimed\"",
        "   (Partial career progress is lost at the reset too: until then prefer AIR goals that finish a milestone.)",
    ])
    return (1e12 if urgent else RATE), text
