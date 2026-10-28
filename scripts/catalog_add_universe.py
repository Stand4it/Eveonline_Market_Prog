"""Add the rest of what EVE offers to activity_catalog.json (owner 2026-10-28: every activity in the game ranked by ISK/min in the long plan, with its prep).
Idempotent: an id already in the catalog is left as it is. Priors are guesses until timed (unmodeled = best ISK/min on the list)."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "activity_catalog.json")

NEW = [
    {"id": "ice_mining", "name": "Ice mining (ice belts / ice anomalies)", "area": "mining", "match": ["ice "], "prior": [300000, 1500000], "minutes": 45, "risk": "low",
     "requires": {"Mining Barge": 1, "Ice Harvesting": 1}, "needs_tool": "ice", "needs_hull": ["Procurer", "Retriever", "Covetor", "Skiff", "Mackinaw", "Hulk"],
     "how": "Warp to an ice field (Agency > Resource Harvesting), fit Ice Harvesters on a mining barge, fill the ore hold, dock, refine or sell the ice."},
    {"id": "gas_huffing", "name": "Gas cloud harvesting (gas sites, high-sec to wormholes)", "area": "mining", "match": ["gas "], "prior": [300000, 3000000], "minutes": 40,
     "risk": "medium", "requires": {"Gas Cloud Harvesting": 1}, "needs_tool": "gas", "needs_hull": ["Venture", "Prospect", "Endurance"],
     "how": "Scan down a gas site (probes), fit Gas Cloud Scoops on a Venture, harvest, dock, sell the gas where it pays most (booster makers buy it)."},
    {"id": "moon_mining", "name": "Moon ore mining (public moon belts after a corp detonation)", "area": "mining", "match": ["moon ore", "moon mining"], "prior": [300000, 2500000],
     "minutes": 45, "risk": "medium", "requires": {"Mining": 4}, "needs_tool": "mining", "needs_hull": ["Venture", "Procurer", "Retriever", "Covetor"],
     "how": "A corporation Athanor/Tatara detonates a moon chunk: the belt is open to anyone in the system for ~2 days. Find one (Agency or local chat), mine it, refine the moon ore."},
    {"id": "ore_anomalies", "name": "Ore anomalies (Agency > Resource Harvesting)", "area": "mining", "match": ["ore anomal", "ore site"], "prior": [150000, 900000], "minutes": 45,
     "risk": "low", "requires": {}, "needs_tool": "mining", "needs_hull": ["Venture", "Procurer", "Retriever", "Covetor"],
     "how": "Agency > Resource Harvesting lists ore anomalies in reach (richer ores than belts); warp there, mine, dock and unload."},
    {"id": "hacking_sites", "name": "Data / relic site hacking (needs analyzers)", "area": "exploration", "match": ["hack", "data analyzer", "relic analyzer"],
     "prior": [400000, 3000000], "minutes": 35, "risk": "medium", "requires": {"Hacking": 1, "Archaeology": 1, "Astrometrics": 1}, "needs_tool": "scanning",
     "prep_items": [["Data Analyzer I", 1], ["Relic Analyzer I", 1]], "needs_hull": ["Imicus", "Heron", "Magnate", "Probe", "Astero"],
     "how": "Scan down a data or relic site, hack the cans (mini game), loot, sell the loot where it pays most."},
    {"id": "wormhole_excursion", "name": "Wormhole excursions (J-space data/relic/gas, scanned exits)", "area": "exploration", "match": ["wormhole", "j-space"],
     "prior": [800000, 6000000], "minutes": 60, "risk": "high", "requires": {"Astrometrics": 3, "Hacking": 2, "Archaeology": 2}, "needs_tool": "scanning",
     "prep_items": [["Data Analyzer I", 1], ["Relic Analyzer I", 1]], "needs_hull": ["Heron", "Imicus", "Magnate", "Probe", "Astero"],
     "how": "Leave all cargo you do not need, take a cheap scanning frigate through a wormhole, bookmark the way back, run data/relic sites, leave before the hole closes."},
    {"id": "agent_l3_security", "name": "Level 3 security missions (high- and low-sec)", "area": "agents", "match": ["level 3 security"], "prior": [2000000, 8000000],
     "minutes": 45, "risk": "high", "requires": {"Gallente Cruiser": 3, "Medium Hybrid Turret": 3},
     "how": "Needs a combat cruiser fit that passes the 99% rule; low-sec missions only when the route and the fit pass the safety rules."},
    {"id": "agent_l4_security", "name": "Level 4 security missions", "area": "agents", "match": ["level 4 security"], "prior": [5000000, 20000000], "minutes": 60,
     "risk": "high", "requires": {"Gallente Battleship": 3, "Large Hybrid Turret": 3}, "how": "Needs a battleship fit that passes the 99% rule and standing 5.0 with the corporation."},
    {"id": "abyssal_t0", "name": "Abyssal deadspace (Tier 0-1 filaments)", "area": "combat", "match": ["abyss", "filament"], "prior": [1000000, 6000000], "minutes": 20,
     "risk": "high", "requires": {"Gallente Destroyer": 3}, "how": "Use a Tranquil/Calm filament in a destroyer or cruiser fit that passes the 99% rule; 20 minutes or the ship dies."},
    {"id": "faction_warfare", "name": "Faction warfare plexing (low-sec)", "area": "combat", "match": ["faction warfare", "plex"], "prior": [500000, 5000000], "minutes": 60,
     "risk": "high", "requires": {"Gallente Frigate": 3}, "how": "Join a militia, run the complexes in low-sec, LP to the faction store. PvP risk: only with a fit and route that pass the rules."},
]


def main():
    with open(PATH, encoding="utf-8") as f:
        d = json.load(f)
    have = {a["id"] for a in d["activities"]}
    added = [a["id"] for a in NEW if a["id"] not in have]
    d["activities"] += [a for a in NEW if a["id"] not in have]
    with open(PATH, "w", encoding="utf-8", newline="\n") as f:
        json.dump(d, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print(f"added {len(added)}: {', '.join(added) or 'none (all present)'}")


if __name__ == "__main__":
    main()
