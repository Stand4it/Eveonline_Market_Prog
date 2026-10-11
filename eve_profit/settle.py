"""`settle`: match market sales to the step that STARTED them. A listed order sells hours later, long after its step was stopped with 0 ISK.
The wallet journal holds every broker fee, sales tax and sale with its time, so:
   * fees paid around a selling step belong to that step (listing it costs money),
   * a later sale (and the tax paid with it) goes to the EARLIEST selling step that listed something and has not sold yet,
   * the later step you ran just to finish the sale (cancel, relist, collect) is merged into it: its minutes join the earlier step and it is removed.
Dry run by default: `settle` shows what it would change, `settle --apply` saves it. Journal entries already used are remembered."""
import json
import time

from .session import INCOME_TYPES, SALE_WORDS, _ts

COST_REFS = ("brokers_fee", "transaction_tax", "market_provider_tax")
COST_DESC = ("market order commission", "market safety tax", "sales tax")
BEFORE_S, AFTER_S, TAX_FOLLOW_S, MAX_OPEN_DAYS = 300, 600, 120, 14


NOT_COST = ("agent", "bounty", "corporation", "escrow", "insurance", "contract", "project")


def is_cost(e):
    """A market fee or tax: broker fees, sales tax and the regional market taxes (any negative entry with 'market', 'broker' or 'transaction_tax'
    in its type or description). Buy-order escrow and mission/corporation taxes are not costs of a sale."""
    ref = (e.get("ref_type") or "").lower()
    d = (e.get("description") or "").lower()
    if e.get("amount", 0) >= 0 or any(w in ref for w in NOT_COST):
        return False
    return ref in COST_REFS or "market" in ref or "broker" in ref or d.startswith(COST_DESC) or "market" in d


def is_sale(e):
    return e.get("ref_type") == "market_transaction" and e.get("amount", 0) > 0


def with_gaps(entries):
    """ESI leaves some wallet charges out of the journal (e.g. the 'Exordium Market Tax'), but every entry carries the balance AFTER it.
    When an entry's balance is lower than the previous entry's balance plus its own amount, the difference is a hidden charge at that time:
    add it as a synthetic market cost (id 'gap-<id>')."""
    out = list(entries)
    es = sorted((e for e in entries if e.get("balance") is not None), key=lambda x: x.get("id", 0))
    for prev, cur in zip(es, es[1:]):
        diff = cur["balance"] - (prev["balance"] + cur.get("amount", 0.0))
        if diff < -1.5:
            out.append({"id": f"gap-{cur.get('id')}", "date": cur["date"], "ref_type": "market_charge_not_in_journal", "amount": diff,
                        "description": "hidden market charge (found from the wallet balance gap)"})
    return out


def sell_steps(rows):
    """Selling steps from activity_log rows (id, activity, isk, hours, ts): -> [{id,name,start,end,isk,hours}] oldest first."""
    out = []
    for r in rows:
        if any(w in r["activity"].lower() for w in SALE_WORDS):
            out.append({"id": r["id"], "name": r["activity"], "start": r["ts"] - r["hours"] * 3600.0, "end": r["ts"], "isk": r["isk"], "hours": r["hours"]})
    return sorted(out, key=lambda s: s["end"])


def attribute(entries, steps, used=()):
    """-> {step_id: {"income": X, "costs": -Y, "ids": [...], "sales": n, "fees": n}} for the journal entries not in `used`."""
    used_s = {str(u) for u in used}
    st = {s["id"]: {"income": 0.0, "costs": 0.0, "ids": [], "sales": 0, "fees": 0} for s in steps}
    by_id = {s["id"]: s for s in steps}
    last_sale = None                                                    # (time, step id)

    def window(t):
        for s in steps:
            if s["start"] - BEFORE_S <= t <= s["end"] + AFTER_S:
                return s["id"]
        return None

    def open_step(t):
        """Earliest selling step that listed something (paid fees) but has not sold yet, ended before t, within MAX_OPEN_DAYS."""
        for s in steps:
            a = st[s["id"]]
            if a["fees"] and not a["sales"] and s["start"] - BEFORE_S <= t and t - s["end"] <= MAX_OPEN_DAYS * 86400:
                return s["id"]
        return None

    for e in sorted((x for x in entries if str(x.get("id")) not in used_s and (is_sale(x) or is_cost(x))), key=lambda x: (_ts(x["date"]), str(x.get("id", 0)).zfill(20))):
        t = _ts(e["date"])
        if is_sale(e):
            sid = open_step(t) or window(t)
            if sid is None:
                continue
            st[sid]["income"] += e["amount"]
            st[sid]["sales"] += 1
            last_sale = (t, sid)
        else:
            if last_sale and e.get("ref_type") == "transaction_tax" and 0 <= t - last_sale[0] <= TAX_FOLLOW_S:
                sid = last_sale[1]
            else:
                sid = window(t) or open_step(t)
                if sid is not None and by_id[sid]["end"] + AFTER_S < t and st[sid]["sales"]:
                    sid = open_step(t)                                  # that step already sold: a later fee is a new listing
            if sid is None:
                continue
            st[sid]["costs"] += e["amount"]
            st[sid]["fees"] += 1
        st[sid]["ids"].append(e.get("id"))
    return {k: v for k, v in st.items() if v["ids"]}


def plan(rows, entries, used=()):
    """-> list of proposals: {"step": step, "income","costs","net", "merge": [steps to fold into it]}."""
    steps = sell_steps(rows)
    by_id = {s["id"]: s for s in steps}
    entries = with_gaps(entries)
    att = attribute(entries, steps, used)
    props = []
    for sid, a in att.items():
        s = by_id[sid]
        merge = []
        for o in steps:                                                 # a later selling step with no entries of its own that ran while the sale happened
            if o["id"] != sid and o["id"] not in att and o["end"] > s["end"] and a["sales"]:
                sale_ts = [_ts(e["date"]) for e in entries if e.get("id") in a["ids"] and is_sale(e)]
                if any(o["start"] - BEFORE_S <= t <= o["end"] + AFTER_S for t in sale_ts):
                    merge.append(o)
        props.append({"step": s, "income": a["income"], "costs": a["costs"], "net": a["income"] + a["costs"], "merge": merge, "ids": a["ids"], "sales": a["sales"], "fees": a["fees"]})
    return sorted(props, key=lambda x: x["step"]["end"])


PAY_BEFORE_S, PAY_AFTER_S = 120, 1800


def is_payout(e):
    """Income the activity itself earned (mission rewards and bonuses, bounties...) or the corporation tax taken from it."""
    d = (e.get("description") or "").lower()
    if e.get("amount", 0) > 0:
        return e.get("ref_type") in INCOME_TYPES
    return e.get("amount", 0) < 0 and ("corporation tax" in d or "corporation_tax" in (e.get("ref_type") or "")) and "agent" in (d + (e.get("ref_type") or ""))


def payout_plan(rows, entries, used=(), skip=()):
    """Steps saved with 0 ISK because the payout reached the journal after `stop` ran (ESI lag): give each such step the payouts posted
    from just before it ended until 30 minutes after. -> [{"step": row, "net": X, "gross": G, "tax": T, "ids": [...]}]"""
    used_s = {str(u) for u in used}
    zero = [r for r in rows if not r["isk"] and r["hours"] > 0 and r["id"] not in set(skip)]
    entries = with_gaps(entries)                                        # ESI hides the corporation-tax lines too: they show up as balance gaps
    gaps = [e for e in entries if str(e.get("id")).startswith("gap-") and str(e["id"]) not in used_s]
    cand = sorted((e for e in entries if is_payout(e) and str(e.get("id")) not in used_s), key=lambda x: (_ts(x["date"]), str(x.get("id", 0)).zfill(20)))
    taken, out = set(), []
    for r in sorted(zero, key=lambda r: r["ts"]):
        lo, hi = r["ts"] - PAY_BEFORE_S, r["ts"] + PAY_AFTER_S
        mine = [e for e in cand if str(e.get("id")) not in taken and lo <= _ts(e["date"]) <= hi]
        gross = sum(e["amount"] for e in mine if e["amount"] > 0)
        times = [_ts(e["date"]) for e in mine if e["amount"] > 0]
        for gp in gaps:                                                 # a hidden charge posted in the same moment as a payout is its corporation tax
            if str(gp["id"]) not in taken and any(abs(_ts(gp["date"]) - t) <= 5 for t in times):
                mine.append(gp)
        tax = sum(e["amount"] for e in mine if e["amount"] < 0)
        if gross > 0:
            taken |= {str(e.get("id")) for e in mine}
            out.append({"step": r, "net": gross + tax, "gross": gross, "tax": tax, "ids": [e.get("id") for e in mine]})
    return out


def _when(t):
    return time.strftime("%m-%d %H:%M", time.localtime(t))


def format_payouts(pays):
    L = []
    for q in pays:
        r = q["step"]
        L.append(f"   #{r['id']} {r['name'] if 'name' in r.keys() else r['activity']} ({_when(r['ts'])}): payouts {q['gross']:+,.0f}" + (f", corporation tax {q['tax']:+,.0f}" if q['tax'] else " (ESI already takes the corporation tax off)") + f" = {q['net']:+,.0f} ISK"
                 f"  (was 0; the journal posted them after `stop`)  = {q['net'] / max(r['hours'] * 60, 1e-9):+,.0f} ISK/min")
    return L


def format_plan(props, apply, pays=()):
    if not props and not pays:
        return "Nothing to settle: no market sales, fees or late payouts in your wallet journal that are not already counted."
    L = ["SETTLE: market sales, fees and late payouts matched to the step they belong to" + ("" if apply else "   (dry run: add --apply to save)")]
    L += format_payouts(pays)
    for pr in props:
        s = pr["step"]
        L.append(f"   #{s['id']} {s['name']} ({_when(s['end'])}): {pr['income']:+,.0f} from {pr['sales']} sale(s), {pr['costs']:+,.0f} in {pr['fees']} fee/tax entries"
                 f" = {pr['net']:+,.0f} ISK  (was {s['isk']:,.0f})")
        for m in pr["merge"]:
            L.append(f"        merge #{m['id']} {m['name']} ({_when(m['end'])}, {m['hours'] * 60:.0f} min, {m['isk']:,.0f} ISK): same sale; its minutes join #{s['id']} and it is removed")
        hrs = s["hours"] + sum(m["hours"] for m in pr["merge"])
        L.append(f"        step total: {hrs * 60:.0f} min, {pr['net']:+,.0f} ISK = {pr['net'] / max(hrs, 1e-9):+,.0f} ISK/hr ({pr['net'] / max(hrs * 60, 1e-9):+,.0f} ISK/min)")
    return "\n".join(L)


def apply_payouts(con, pays):
    used = {str(u) for u in json.loads((con.execute("SELECT value FROM meta WHERE key='settled_ids'").fetchone() or ["[]"])[0])}
    for q in pays:
        con.execute("UPDATE activity_log SET isk=? WHERE id=?", (q["net"], q["step"]["id"]))
        used |= {str(i) for i in q["ids"] if i is not None}
    con.execute("INSERT OR REPLACE INTO meta VALUES('settled_ids', ?)", (json.dumps(sorted(used)[-3000:]),))
    con.commit()


def apply(con, props):
    """Save: replace each step's ISK with its net, add the merged steps' minutes, remove the merged steps, remember the used journal entries."""
    used = {str(u) for u in json.loads((con.execute("SELECT value FROM meta WHERE key='settled_ids'").fetchone() or ["[]"])[0])}
    for pr in props:
        s = pr["step"]
        hours = s["hours"] + sum(m["hours"] for m in pr["merge"])
        con.execute("UPDATE activity_log SET isk=?, hours=? WHERE id=?", (pr["net"], hours, s["id"]))
        for m in pr["merge"]:
            con.execute("DELETE FROM activity_log WHERE id=?", (m["id"],))
        used |= {str(i) for i in pr["ids"] if i is not None}
    con.execute("INSERT OR REPLACE INTO meta VALUES('settled_ids', ?)", (json.dumps(sorted(used)[-3000:]),))
    con.commit()


def show(esi, cid, n=40):
    """The newest journal entries, unfiltered (id, date, type, amount, description, and whether settle counts it as a sale 'S' or a cost 'C')."""
    entries = esi.paged(f"/characters/{cid}/wallet/journal/")
    keep = with_gaps(entries)                                           # everything, unfiltered: we are looking for what ESI calls the fees we miss
    L = [f"{'id':>14} {'date (UTC)':<20} {'ref_type':<34} {'amount':>12} ?  description"]
    for e in sorted(keep, key=lambda x: (x["date"], str(x.get("id", 0))), reverse=True)[:n]:
        mark = "S" if is_sale(e) else ("C" if is_cost(e) else " ")
        L.append(f"{e.get('id', 0):>14} {e['date'][:19]:<20} {e.get('ref_type', ''):<34} {e.get('amount', 0):>12,.0f} {mark}  {e.get('description', '')[:50]}")
    return "\n".join(L)


def run(con, esi, cid, do_apply=False):
    rows = con.execute("SELECT id, activity, isk, hours, ts FROM activity_log ORDER BY ts").fetchall()
    entries = esi.paged(f"/characters/{cid}/wallet/journal/")
    used = json.loads((con.execute("SELECT value FROM meta WHERE key='settled_ids'").fetchone() or ["[]"])[0])
    props = plan(rows, entries, used)
    skip = {pr["step"]["id"] for pr in props} | {m["id"] for pr in props for m in pr["merge"]}
    pays = payout_plan(rows, entries, used, skip)
    if do_apply:
        if props:
            apply(con, props)
        if pays:
            apply_payouts(con, pays)
    return format_plan(props, do_apply and bool(props or pays), pays)


def recent_payouts(entries, since_ts):
    """Payout entries (rewards, bounties, AIR/daily-goal rewards) posted since since_ts, newest first: [(time, ref_type, amount, description)]."""
    out = []
    for e in entries:
        if e.get("amount", 0) > 0 and e.get("ref_type") in INCOME_TYPES and _ts(e["date"]) >= since_ts:
            out.append((_ts(e["date"]), e["ref_type"], e["amount"], (e.get("description") or "")[:40]))
    return sorted(out, reverse=True)


def format_recent(rows):
    if not rows:
        return "   No payouts in your wallet journal in that time (ESI can lag a few minutes)."
    L = ["   Payouts in your wallet journal (newest first). To put one on this run:  python -m eve_profit fixlast --isk AMOUNT"]
    L += [f"      {time.strftime('%m-%d %H:%M', time.localtime(t))} local   {amt:>10,.0f}   {ref}   {desc}" for t, ref, amt, desc in rows[:8]]
    return "\n".join(L)
