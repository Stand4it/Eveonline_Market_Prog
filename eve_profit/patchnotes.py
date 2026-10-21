"""EVE patch notes and news, read once a day from CCP's public RSS feeds (no login, no browser): www.eveonline.com/rss/patch-notes carries the
full text of the current release page, split into dated sections ('PATCH NOTES FOR 2026-10-20.1'); www.eveonline.com/rss lists the news.
New sections are saved to data/patchnotes/<section>.txt; lines that touch ISK making (markets, taxes, missions, mining, LP, drops, events, ESI)
are picked out, and `next` shows one notice line until you read them.
python -m eve_profit.patchnotes            check now (at most once a day unless --force) and print what is new
python -m eve_profit.patchnotes --show     print the money-relevant lines of the sections not read yet, and mark them read"""
import html
import json
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "data", "patchnotes")
STATE = os.path.join(DIR, "state.json")
FEEDS = {"patch": "https://www.eveonline.com/rss/patch-notes", "news": "https://www.eveonline.com/rss"}
EVERY_S = 20 * 3600
RECENT_S = 7 * 86400          # older updates are saved but not flagged as new
KEYWORDS = ("market", "tax", "broker", "fee", "price", "isk", "loyalty", " lp", "agent", "mission", "mining", "ore", "minerals", "reprocess",
            "drop", "loot", "bounty", "bounties", "skin", "crate", "booster", "skill", "air ", "career", "daily goal", "freelance", "event",
            "harvest", "contract", "hauling", "courier", "industry", "blueprint", "manufactur", "esi", "api", "highsec", "high-sec", "npc buyer")
SECTION = re.compile(r"PATCH NOTES FOR (\d{4}-\d{2}-\d{2}\.\d+)", re.I)


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (eve_profit patch-notes reader)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _text(desc_html):
    t = html.unescape(desc_html or "")
    t = re.sub(r"<\s*(br|/p|/li|/h\d|/div)\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"<li[^>]*>", "\n- ", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    return re.sub(r"\n\s*\n+", "\n", t).strip()


def _items(raw):
    root = ET.fromstring(raw)
    return [{"title": (i.findtext("title") or "").strip(), "link": (i.findtext("link") or "").strip(),
             "date": (i.findtext("pubDate") or "").strip(), "text": _text(i.findtext("description"))} for i in root.iter("item")]


def _state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except (OSError, ValueError):
        return {"ts": 0, "sections": {}, "news": [], "unread": []}


def _save(st):
    os.makedirs(DIR, exist_ok=True)
    json.dump(st, open(STATE, "w", encoding="utf-8"), indent=1)


def relevant(text, limit=12):
    """The lines of a section that touch ISK making."""
    out = []
    for ln in text.splitlines():
        low = " " + ln.lower()
        if len(ln.strip()) > 12 and any(k in low for k in KEYWORDS):
            out.append(ln.strip()[:220])
        if len(out) >= limit:
            break
    return out


def check(force=False, quiet=False):
    """Read the feeds (at most once a day unless force). -> list of new section ids (also new news titles are recorded)."""
    st = _state()
    if not force and time.time() - st.get("ts", 0) < EVERY_S:
        return []
    new = []
    try:
        for it in _items(_get(FEEDS["patch"]))[:1]:                     # the current release page carries every dated update of the release
            parts = SECTION.split(it["text"])                           # [intro, id1, body1, id2, body2, ...]
            for sid, body in zip(parts[1::2], parts[2::2]):
                if sid in st["sections"]:
                    continue
                os.makedirs(DIR, exist_ok=True)
                with open(os.path.join(DIR, f"{sid}.txt"), "w", encoding="utf-8") as f:
                    f.write(f"{it['title']} - PATCH NOTES FOR {sid}\n{it['link']}\n\n{body.strip()}\n")
                st["sections"][sid] = {"title": it["title"], "link": it["link"], "relevant": relevant(body)}
                if st["sections"][sid]["relevant"] and sid[:10] >= time.strftime("%Y-%m-%d", time.gmtime(time.time() - RECENT_S)):
                    st.setdefault("unread", []).append(sid)             # only recent updates are news; older ones are saved for reference
                new.append(sid)
        for it in _items(_get(FEEDS["news"]))[:15]:
            if it["title"] and it["title"] not in st.get("news", []):
                st.setdefault("news", []).append(it["title"])
                try:
                    from email.utils import parsedate_to_datetime
                    recent = time.time() - parsedate_to_datetime(it["date"]).timestamp() < RECENT_S
                except Exception:                                       # noqa: BLE001
                    recent = True
                if recent:
                    st.setdefault("news_new", []).append({"title": it["title"], "link": it["link"], "date": it["date"]})
        st["ts"] = time.time()
        _save(st)
    except Exception as e:                                              # noqa: BLE001
        if not quiet:
            print(f"patch notes: could not read the feeds ({type(e).__name__}: {e})")
    return new


def notice():
    """One line for `next` while money-relevant patch notes or news are unread, else ''."""
    st = _state()
    un, nn = st.get("unread", []), st.get("news_new", [])
    if not un and not nn:
        return ""
    bits = []
    if un:
        bits.append(f"{len(un)} patch-note update(s) touch ISK making ({', '.join(sorted(un)[-3:])})")
    if nn:
        bits.append(f"{len(nn)} new news post(s) (e.g. {nn[-1]['title'][:60]})")
    return "NEW FROM CCP: " + "; ".join(bits) + ".  Read:  python -m eve_profit.patchnotes --show"


def show():
    st = _state()
    L = []
    for sid in sorted(st.get("unread", [])):
        s = st["sections"].get(sid, {})
        L.append(f"PATCH NOTES FOR {sid}  ({s.get('link', '')}; full text: data/patchnotes/{sid}.txt)")
        L += [f"   {x}" for x in s.get("relevant", [])]
    for n in st.get("news_new", []):
        L.append(f"NEWS: {n['title']}  {n['link']}")
    st["unread"], st["news_new"] = [], []
    _save(st)
    return "\n".join(L) or "Nothing new from CCP since you last looked."


if __name__ == "__main__":
    if "--show" in sys.argv:
        print(show())
    else:
        got = check(force="--force" in sys.argv)
        print(f"patch notes: {len(got)} new section(s): {', '.join(got) or 'none'}")
        print(notice() or "nothing unread")
