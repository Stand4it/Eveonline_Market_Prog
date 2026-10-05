"""Pull stock recommendations out of newsletter emails into recommendations.csv.

Connects over IMAP (Gmail: create an App Password and enable IMAP), runs the
search from config.json, and extracts tickers written like `$AAPL`,
`(NYSE: KO)` or `(NASDAQ: MSFT)`. Each ticker found becomes a row dated with
the email's date. Rows already in the CSV are skipped, so it is safe to rerun.

    export STOCK_EMAIL_USER=you@gmail.com
    export STOCK_EMAIL_PASSWORD=<app password>
    python email_ingest.py            # append new picks
    python email_ingest.py --dry-run  # just print what it would add

Review the CSV after ingesting: delete any ticker that was only mentioned,
not recommended.
"""
from __future__ import annotations

import argparse
import csv
import email
import imaplib
import os
import re
from datetime import date, timedelta
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path

from tracker import HERE, Config, load_recs

TICKER_PATTERNS = [
    re.compile(r"\$([A-Z]{1,5}(?:\.[A-Z])?)\b"),
    re.compile(
        r"\((?:NYSE|NASDAQ|Nasdaq|NYSEARCA|NYSE American|AMEX|BATS|Cboe)\s*:\s*"
        r"([A-Z]{1,5}(?:\.[A-Z])?)\)"
    ),
]
# Cashtags that are almost always noise in newsletters.
IGNORE = {"USD", "CAD", "EUR", "GBP", "SPY", "QQQ", "DIA", "VIX"}


def extract_tickers(text: str) -> list[str]:
    seen: list[str] = []
    for pat in TICKER_PATTERNS:
        for t in pat.findall(text):
            t = t.replace(".", "-")  # BRK.B -> BRK-B (Yahoo format)
            if t not in IGNORE and t not in seen:
                seen.append(t)
    return seen


def message_text(msg: email.message.Message) -> str:
    parts = []
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        text = payload.decode(part.get_content_charset() or "utf-8", "replace")
        if ctype == "text/html":
            text = unescape(re.sub(r"<[^>]+>", " ", text))
        parts.append(text)
    return "\n".join(parts)


def fetch_recommendations(cfg: Config, user: str, password: str):
    ec = cfg.email
    since = (date.today() - timedelta(days=int(ec.get("days_back", 14))))
    criteria = f'(SINCE "{since.strftime("%d-%b-%Y")}") {ec.get("search", "ALL")}'
    with imaplib.IMAP4_SSL(ec.get("imap_host", "imap.gmail.com")) as imap:
        imap.login(user, password)
        imap.select(ec.get("mailbox", "INBOX"), readonly=True)
        _, ids = imap.search(None, criteria)
        for num in ids[0].split():
            _, data = imap.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(data[0][1])
            sent = parsedate_to_datetime(msg["Date"]).date()
            subject = str(make_header(decode_header(msg.get("Subject", ""))))
            sender = email.utils.parseaddr(msg.get("From", ""))[1]
            for ticker in extract_tickers(subject + "\n" + message_text(msg)):
                yield sent, ticker, sender, subject


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--recs", type=Path, default=HERE / "recommendations.csv")
    p.add_argument("--config", type=Path, default=HERE / "config.json")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    cfg = Config.load(args.config)
    user = os.environ["STOCK_EMAIL_USER"]
    password = os.environ["STOCK_EMAIL_PASSWORD"]
    have = {(r.rec_date, r.ticker) for r in load_recs(args.recs)}

    new_rows = []
    for sent, ticker, sender, subject in fetch_recommendations(cfg, user, password):
        if (sent, ticker) in have:
            continue
        have.add((sent, ticker))
        new_rows.append([sent.isoformat(), ticker, sender, subject[:80]])

    for row in new_rows:
        print("NEW", *row)
    if new_rows and not args.dry_run:
        with args.recs.open("a", newline="") as f:
            csv.writer(f).writerows(new_rows)
    print(f"{len(new_rows)} new recommendation(s)" + (" (dry run)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
