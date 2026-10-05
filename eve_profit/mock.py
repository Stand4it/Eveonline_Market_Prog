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
    (28999, "Skill Injector (cheap test item)", 0.01, 4_000_000, 0),
]
SEC_LAYERS = [0.9, 0.8, 0.6, 0.5, 0.3, 0.7, 0.9, 0.4, 0.8]


def load_mock(con, seed=7, systems=30):
    rnd = random.Random(seed)
    con.executescript("DELETE FROM systems;DELETE FROM gates;DELETE FROM stations;"
                      "DELETE FROM types;DELETE FROM orders;DELETE FROM inventory;"
                      "DELETE FROM system_kills;DELETE FROM bp_materials;"
                      "DELETE FROM bp_products;DELETE FROM my_blueprints;DELETE FROM prices;")
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
        con.execute("INSERT INTO stations VALUES(?,?,?)", (60000000 + i, i, f"Station {i}"))
    for t in TYPES:
        con.execute("INSERT INTO types(type_id,name,volume,is_ore) VALUES(?,?,?,?)",
                    (t[0], t[1], t[2], t[4]))
    con.executemany("INSERT INTO bp_materials VALUES(90002,?,?)",
                    [(34, 1000), (35, 500), (36, 50)])
    con.execute("INSERT INTO bp_products VALUES(90002,90001,1,3600)")
    con.execute("INSERT INTO my_blueprints VALUES(90002,10,20,-1)")
    con.executemany("INSERT INTO prices VALUES(?,?)", [(t[0], t[3]) for t in TYPES])
    con.execute("INSERT INTO system_kills VALUES(5,9,2,?)", (time.time(),))
    refresh_mock_orders(con, rnd)
    con.execute("INSERT INTO inventory VALUES(3689,1,200)")
    con.commit()


def refresh_mock_orders(con, rnd=None):
    """Re-roll prices (simulates the live market moving)."""
    rnd = rnd or random.Random()
    con.execute("DELETE FROM orders")
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
