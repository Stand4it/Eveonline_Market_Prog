import sqlite3

from eve_profit import orders


def test_cache_key_ignores_other_writes_but_sees_order_writes(tmp_path):
    db = str(tmp_path / "x.db")
    a, b = sqlite3.connect(db), sqlite3.connect(db)
    a.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
    a.commit()
    k = orders._cache_key(a)
    b.execute("INSERT INTO meta VALUES('wallet','1')")             # a sync's wallet/assets/meta write in another process
    b.commit()
    assert orders._cache_key(a) == k
    orders._move_rev(b)                                             # another process wrote orders (what bump(con) does there)
    b.commit()
    assert orders._cache_key(a) != k


def test_frozen_run_ignores_other_processes_but_not_its_own_writes(tmp_path, monkeypatch):
    db = str(tmp_path / "x.db")
    a, b = sqlite3.connect(db), sqlite3.connect(db)
    a.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
    a.commit()
    monkeypatch.setattr(orders, "_FROZEN", [True])
    k = orders._cache_key(a)
    orders._move_rev(b)                                             # a scan in another process saved a region
    b.commit()
    assert orders._cache_key(a) == k
    orders.bump(a)                                                  # this run wrote orders itself
    assert orders._cache_key(a) != k
