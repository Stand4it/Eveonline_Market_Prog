"""`fit`: what is fitted to the ship you are flying (read from your asset list), and what it means."""

KINDS = [("salvager", "Salvager (salvages wrecks)"), ("tractor", "Tractor Beam (pulls wrecks/cans in)"),
         ("miner", "Mining laser/miner"), ("strip", "Strip miner"), ("cargo", "Cargo expander"),
         ("warp core stabilizer", "Warp core stabilizer"), ("scanner", "Scanner/probe launcher"),
         ("afterburner", "Afterburner"), ("microwarpdrive", "Microwarpdrive"), ("shield", "Shield module"),
         ("armor", "Armor module")]


def describe_fit(con, p):
    rows = con.execute("SELECT f.flag,f.quantity,t.name FROM fitted f LEFT JOIN types t ON t.type_id=f.type_id "
                       "ORDER BY f.flag").fetchall()
    if not rows:
        return ("No fitting data. It is read during `sync` from the ship you are flying (you must be logged in with the "
                "assets permission). If you just changed your fit, run `sync` again.")
    L = [f"Ship: {p.ship_name}", ""]
    slots = [r for r in rows if "Slot" in r["flag"]]
    for r in slots:
        L.append(f"   {r['flag']:<10} {r['name'] or '?'}")
    other = [r for r in rows if "Slot" not in r["flag"]]
    if other:
        L.append(f"\n   (also in {len(other)} stacks of cargo/drone bay)")
    names = " | ".join((r["name"] or "").lower() for r in slots)
    found = [label for key, label in KINDS if key in names]
    L += ["", "What this ship can do: " + (", ".join(found) if found else "nothing special is fitted (no salvager, tractor beam or miner)")]
    if "salvager" not in names:
        L.append("No salvager fitted: it cannot salvage wrecks. A salvager is a high-slot module; a tractor beam alone only pulls them in.")
    return "\n".join(L)
