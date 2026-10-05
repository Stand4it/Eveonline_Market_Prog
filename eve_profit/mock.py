"""Deterministic offline universe + market so everything runs without EVE/ESI."""
import random
import time

# (type_id, name, m3, base price, is_ore)
TYPES = [
    (34, "Tritanium", 0.01, 5, 0), (35, "Pyerite", 0.01, 10, 0),
    (36, "Mexallon", 0.01, 60, 0), (37, "Isogen", 0.01, 80, 0),
    (1230, "Veldspar", 0.1, 12, 1), (1228, "Scordite", 0.15, 18, 1),
    (18, "Plagioclase", 0.35, 30, 1), (11399, "Morphite", 0.01, 9000, 0),
    (3645, "Water", 1.0, 120, 0), (3689, "Mechanical Parts", 1.0, 1500, 0),
    (2268, "Nanite Repair Paste", 0.01, 400, 0), (16275, "Strontium Clathrates", 0.4, 500, 0),
    (90001, "Mock Widget", 5.0, 16000, 0),
    (80001, "Tripped Power Circuit", 0.01, 3000, 0),
    (80002, "Charred Micro Circuit", 0.01, 2500, 0),
    (28999, "Skill Injector (cheap test item)", 0.01, 4_000_000, 0),
]
SEC_LAYERS = [0.9, 0.8, 0.6, 0.5, 0.3, 0.7, 0.9, 0.4, 0.8]


def load_mock(con, seed=7, systems=30):
    rnd = random.Random(seed)
    con.executescript("DELETE FROM systems;DELETE FROM gates;DELETE FROM stations;"
                      "DELETE FROM types;DELETE FROM orders;DELETE FROM inventory;"
                      "DELETE FROM system_kills;DELETE FROM bp_materials;"
                      "DELETE FROM bp_products;DELETE FROM my_blueprints;DELETE FROM prices;DELETE FROM structures;DELETE FROM agents;DELETE FROM lp_offers;DELETE FROM lp_offer_items;DELETE FROM lp_balance;DELETE FROM standings;DELETE FROM skill_reqs;DELETE FROM type_skills;DELETE FROM character_skills;DELETE FROM contracts;DELETE FROM contract_items;")
    con.execute("INSERT INTO systems VALUES(1,'Home',0.9,10000001)")
    for i in range(2, systems + 1):
        con.execute("INSERT INTO systems VALUES(?,?,?,?)",
                    (i, f"Sys{i:02d}", SEC_LAYERS[(i - 2) % len(SEC_LAYERS)], 10000001))
        parent = rnd.randint(max(1, i - 6), i - 1)
        con.execute("INSERT INTO gates VALUES(?,?)", (parent, i))
        if rnd.random() < 0.3:
            other = rnd.randint(1, i - 1)
            if other != parent:
                con.execute("INSERT OR IGNORE INTO gates VALUES(?,?)", (other, i))
    for i in range(1, systems + 1):
        con.execute("INSERT INTO stations VALUES(?,?,?,?)", (60000000 + i, i, f"Station {i}", 1000001 + i % 3))
    for t in TYPES:
        con.execute("INSERT INTO types(type_id,name,volume,is_ore) VALUES(?,?,?,?)",
                    (t[0], t[1], t[2], t[4]))
    con.executemany("INSERT INTO bp_materials VALUES(90002,?,?)",
                    [(34, 1000), (35, 500), (36, 50)])
    con.execute("INSERT INTO bp_products VALUES(90002,90001,1,3600)")
    con.execute("INSERT INTO my_blueprints VALUES(90002,10,20,-1)")
    con.executemany("INSERT INTO prices VALUES(?,?)", [(t[0], t[3]) for t in TYPES])
    far = time.time() + 86400 * 10
    # underpriced bundle at Home (worth ~5x tritanium+pyerite base; priced at 40% of base value)
    con.execute("INSERT INTO contracts VALUES(5001,10000001,'item_exchange',200000,0,0,0,0,1,1,?,0,'',1,?)",
                (far, time.time()))
    con.executemany("INSERT INTO contract_items VALUES(5001,?,?,1,0)", [(34, 40000), (35, 20000)])
    con.execute("INSERT INTO contracts VALUES(5002,10000001,'courier',0,2500000,5000000,3000,0,2,8,?,3,'',1,?)",
                (far, time.time()))
    con.executemany("INSERT INTO types(type_id,name,volume) VALUES(?,?,0.01)",
                    [(3380, "Industry"), (3387, "Mass Production"), (3388, "Advanced Industry")])
    con.execute("INSERT INTO skill_reqs VALUES(90002,3380,3)")
    # LP: corp 1000001 store sells a Widget for 1000 LP + 1000 ISK + 100 Tritanium; we hold 5000 LP
    con.execute("INSERT INTO lp_offers VALUES(1000001,1,90001,1,1000,1000,0)")
    con.execute("INSERT INTO lp_offer_items VALUES(1000001,1,34,100)")
    con.execute("INSERT INTO lp_offers VALUES(1000001,2,11399,1,500,0,0)")   # Morphite, 500 LP
    con.execute("INSERT INTO lp_balance VALUES(1000001,5000)")
    # mission agents: (id, corp, system, level)
    for aid, corp, sysid, lvl in [(3001, 1000001, 1, 2), (3002, 1000002, 2, 3), (3003, 1000001, 8, 4)]:
        con.execute("INSERT INTO agents VALUES(?,?,?,?,?,5)", (aid, corp, 60000000 + sysid, sysid, lvl))
    # a player structure in Sys02 whose buyers pay 2x for Tritanium (tests structure scanning)
    con.execute("INSERT INTO structures VALUES(1000000000001,'Mock Citadel',2,99,1,?,?)",
                (time.time(), time.time()))
    con.execute("INSERT INTO orders VALUES(990000001,34,1000000000001,2,10000001,1,10.0,500000,1,'',?)",
                (time.time(),))
    con.execute("INSERT INTO system_kills VALUES(5,9,2,?)", (time.time(),))
    refresh_mock_orders(con, rnd)
    con.execute("INSERT INTO inventory VALUES(3689,1,200)")
    con.commit()


def refresh_mock_orders(con, rnd=None):
    """Re-roll prices (simulates the live market moving)."""
    rnd = rnd or random.Random()
    con.execute("DELETE FROM orders WHERE location_id < 1000000000000")   # keep structure orders
    now, oid = time.time(), 1
    for (sid,) in con.execute("SELECT system_id FROM systems").fetchall():
        for tid, _, _, base, _ in TYPES:
            if rnd.random() < 0.25:
                continue
            mid = base * rnd.uniform(0.85, 1.15)
            for _ in range(3):
                con.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (oid, tid, 60000000 + sid, sid, 10000001, 0,
                             round(mid * rnd.uniform(1.0, 1.08), 2),
                             rnd.randint(50, 20000) if base < 1000 else rnd.randint(1, 30),
                             1, "", now))
                oid += 1
                con.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (oid, tid, 60000000 + sid, sid, 10000001, 1,
                             round(mid * rnd.uniform(0.92, 1.0), 2),
                             rnd.randint(50, 20000) if base < 1000 else rnd.randint(1, 30),
                             1, "", now))
                oid += 1
    con.commit()
