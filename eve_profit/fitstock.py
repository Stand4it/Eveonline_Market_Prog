"""`fitstock`: the modules, charges, drones and ships you OWN (assets), with slot type and the numbers that matter for fighting, so a fit can use what is already in
your hangars. Read from ESI assets + type dogma; prints the best candidates per slot (damage / tank / speed / cap) next to what the fit window shows."""
SLOT_EFFECT = {12: "high", 13: "mid", 11: "low", 2663: "rig", 3772: "subsystem"}
ATTR = {50: "cpu", 30: "power", 64: "dmg x", 51: "rof ms", 20: "speed x", 84: "armor rep", 68: "shield boost", 72: "shield hp+", 265: "armor hp+",
        76: "range m", 54: "optimal m", 158: "falloff", 1795: "cap use", 6: "cap use", 796: "mass+", 37: "max speed+", 439: "dmg bonus"}
CATS = {6: "ship", 7: "module", 8: "charge", 18: "drone", 87: "fighter"}


def _assets(esi, cid):
    return esi.paged(f"/characters/{cid}/assets/")


def collect(con, esi, cid, loc_names=True):
    """-> {type_id: {"name","cat","qty","where": set(location_id)}} for modules/charges/drones/ships (ESI assets)."""
    out = {}
    for a in _assets(esi, cid):
        tid = a["type_id"]
        row = con.execute("SELECT name,category_id FROM types WHERE type_id=?", (tid,)).fetchone()
        if not row or row[1] not in CATS:
            continue
        d = out.setdefault(tid, {"name": row[0], "cat": CATS[row[1]], "qty": 0, "where": set(), "fitted": 0})
        d["qty"] += a.get("quantity", 1)
        d["where"].add(a["location_id"])
        if str(a.get("location_flag", "")).endswith(("Slot0", "Slot1", "Slot2", "Slot3", "Slot4", "Slot5", "Slot6", "Slot7", "Slot8")) or "Slot" in str(a.get("location_flag", "")):
            d["fitted"] += a.get("quantity", 1)
    return out


def describe(esi, tid):
    """slot + key numbers of one type from ESI dogma."""
    try:
        t = esi.type_info(tid)
    except Exception:                                                   # noqa: BLE001
        return "?", {}
    slot = next((SLOT_EFFECT[e["effect_id"]] for e in t.get("dogma_effects", []) if e["effect_id"] in SLOT_EFFECT), "")
    nums = {ATTR[x["attribute_id"]]: round(x["value"], 2) for x in t.get("dogma_attributes", []) if x["attribute_id"] in ATTR}
    return slot, nums


def report(con, esi, cid):
    owned = collect(con, esi, cid)
    if not owned:
        return "No modules, charges, drones or ships found in your assets (or the assets permission is missing: run  python -m eve_profit login)."
    lines = ["WHAT YOU OWN THAT CAN GO ON A SHIP (fitted pieces are counted too):", ""]
    for cat in ("ship", "module", "charge", "drone", "fighter"):
        items = sorted((d for d in owned.items() if d[1]["cat"] == cat), key=lambda x: x[1]["name"])
        if not items:
            continue
        lines.append(f"{cat.upper()}S")
        for tid, d in items:
            if cat in ("module", "drone", "charge"):
                slot, nums = describe(esi, tid)
            else:
                slot, nums = "", {}
            extra = ", ".join(f"{k} {v}" for k, v in nums.items())
            fit = f" ({d['fitted']} fitted)" if d["fitted"] else ""
            lines.append(f"   {d['qty']:>6,} x {d['name']}{fit}" + (f"  [{slot}]" if slot else "") + (f"  {extra}" if extra else ""))
        lines.append("")
    lines.append("Compare with the in-game Fitting window (Simulate): drag a piece on, read dps / ehp / cap, and send me the screen; the model uses the game's own numbers.")
    return "\n".join(lines)
