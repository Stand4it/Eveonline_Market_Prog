"""Build data/wreck_difficulty.json from the SDE zip: ship type_id -> the salvage 'access difficulty' of the wreck it leaves (owner 2026-10-29).
The game's chance to salvage a wreck = difficulty + 5% x Salvaging level (Salvager I; the skill's '100% per level' doubles, triples... the module's 5%).
T1 frigate/destroyer/rookie/shuttle wrecks 30, cruiser/battlecruiser/hauler/barge 20, battleship and bigger 10; T2, T3 and faction hulls leave
'Elite'/'Advanced' wrecks at -10 (so Salvaging 3 is the first level that can take them, at 5%).
python scripts/build_wreck_map.py [E:/EveProfit/sde-jsonl.zip]"""
import json
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "wreck_difficulty.json")
SMALL = ("frigate", "destroyer", "corvette", "shuttle", "interceptor", "covert ops", "stealth bomber", "electronic attack", "logistics frigate",
         "expedition frigate", "interdictor", "tactical destroyer", "command destroyer", "assault frigate")
BIG = ("battleship", "freighter", "carrier", "dreadnought", "titan", "supercarrier", "force auxiliary", "marauder", "black ops", "jump freighter",
       "capital industrial", "industrial command")


def diff_for(group, tech, meta):
    """-> wreck difficulty for a ship of this group name / tech level / meta group, or None if not a known ship class."""
    g = (group or "").lower()
    if tech and tech >= 2 or meta not in (None, 1):
        return -10.0
    if any(k in g for k in BIG):
        return 10.0
    if any(k in g for k in SMALL):
        return 30.0
    if any(k in g for k in ("cruiser", "industrial", "hauler", "mining barge", "exhumer", "battlecruiser")):
        return 20.0
    return None


def build(zpath):
    z = zipfile.ZipFile(zpath)
    rows = lambda n: (json.loads(ln) for ln in z.open(n))                   # noqa: E731
    groups = {r["_key"]: ((r.get("name") or {}).get("en", ""), r.get("categoryID")) for r in rows("groups.jsonl")}
    out = {}
    for r in rows("types.jsonl"):
        gname, cat = groups.get(r.get("groupID"), ("", None))
        if cat != 6:
            continue
        d = diff_for(gname, r.get("techLevel"), r.get("metaGroupID"))
        if d is not None:
            out[str(r["_key"])] = d
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"))
    return out


if __name__ == "__main__":
    m = build(sys.argv[1] if len(sys.argv) > 1 else "E:/EveProfit/sde-jsonl.zip")
    print(f"{len(m)} ship hulls -> {OUT}")
    for tid in ("603", "627", "29990", "17920", "606"):                     # Merlin, Thorax, Loki, Bhaalgorn, Velator
        print("  ", tid, m.get(tid))
