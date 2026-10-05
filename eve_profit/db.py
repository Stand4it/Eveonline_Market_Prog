"""SQLite schema and helpers."""
import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS systems(
  system_id INTEGER PRIMARY KEY, name TEXT NOT NULL, security REAL NOT NULL,
  region_id INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS ix_sys_name ON systems(name);
CREATE TABLE IF NOT EXISTS gates(
  from_id INTEGER NOT NULL, to_id INTEGER NOT NULL, PRIMARY KEY(from_id,to_id));
CREATE TABLE IF NOT EXISTS stations(
  station_id INTEGER PRIMARY KEY, system_id INTEGER NOT NULL, name TEXT);
CREATE TABLE IF NOT EXISTS types(
  type_id INTEGER PRIMARY KEY, name TEXT, volume REAL NOT NULL DEFAULT 1,
  group_id INTEGER, category_id INTEGER, is_ore INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS orders(
  order_id INTEGER PRIMARY KEY, type_id INTEGER NOT NULL, location_id INTEGER,
  system_id INTEGER NOT NULL, region_id INTEGER NOT NULL, is_buy INTEGER NOT NULL,
  price REAL NOT NULL, volume_remain INTEGER NOT NULL, min_volume INTEGER NOT NULL DEFAULT 1,
  issued TEXT, fetched_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS ix_ord_type ON orders(type_id, is_buy);
CREATE INDEX IF NOT EXISTS ix_ord_sys ON orders(system_id);
CREATE TABLE IF NOT EXISTS inventory(
  type_id INTEGER NOT NULL, system_id INTEGER NOT NULL, quantity INTEGER NOT NULL,
  PRIMARY KEY(type_id, system_id));
CREATE TABLE IF NOT EXISTS system_kills(
  system_id INTEGER PRIMARY KEY, ship_kills INTEGER, pod_kills INTEGER, fetched_at REAL);
CREATE TABLE IF NOT EXISTS opportunities(
  id INTEGER PRIMARY KEY AUTOINCREMENT, scanned_at REAL NOT NULL, kind TEXT NOT NULL,
  description TEXT NOT NULL, profit_isk REAL, risk_cost_isk REAL, jumps INTEGER,
  hours REAL, isk_per_jump REAL, isk_per_hour REAL, route TEXT, detail TEXT);
CREATE INDEX IF NOT EXISTS ix_opp_scan ON opportunities(scanned_at);
CREATE TABLE IF NOT EXISTS bp_materials(
  blueprint_id INTEGER NOT NULL, material_id INTEGER NOT NULL, quantity INTEGER NOT NULL,
  PRIMARY KEY(blueprint_id, material_id));
CREATE TABLE IF NOT EXISTS bp_products(
  blueprint_id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL, quantity INTEGER NOT NULL,
  base_time INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS my_blueprints(
  blueprint_id INTEGER NOT NULL, me INTEGER NOT NULL DEFAULT 0, te INTEGER NOT NULL DEFAULT 0,
  runs INTEGER NOT NULL DEFAULT -1);
CREATE TABLE IF NOT EXISTS prices(type_id INTEGER PRIMARY KEY, adjusted_price REAL);
CREATE TABLE IF NOT EXISTS activities(
  name TEXT PRIMARY KEY, kind TEXT NOT NULL, min_sec REAL NOT NULL, max_sec REAL NOT NULL,
  isk_per_hour REAL NOT NULL, wrecks_per_hour REAL NOT NULL DEFAULT 0,
  p_loss_per_hour REAL NOT NULL DEFAULT 0.001, min_dps REAL NOT NULL DEFAULT 0,
  session_hours REAL NOT NULL DEFAULT 1.0,
  enemy_ehp REAL NOT NULL DEFAULT 0, threat_dps REAL NOT NULL DEFAULT 0,
  waves_per_hour REAL NOT NULL DEFAULT 4);
CREATE TABLE IF NOT EXISTS salvage_items(
  type_name TEXT PRIMARY KEY, qty_per_wreck REAL NOT NULL, chance REAL NOT NULL DEFAULT 1.0);
CREATE TABLE IF NOT EXISTS activity_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, activity TEXT NOT NULL, isk REAL NOT NULL,
  hours REAL NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


def connect(path: str) -> sqlite3.Connection:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    for col, ddl in (("enemy_ehp", "REAL NOT NULL DEFAULT 0"), ("threat_dps", "REAL NOT NULL DEFAULT 0"),
                     ("waves_per_hour", "REAL NOT NULL DEFAULT 4")):
        try:  # migrate databases created before the win-odds model
            con.execute(f"ALTER TABLE activities ADD COLUMN {col} {ddl}")
        except sqlite3.OperationalError:
            pass
    return con


def set_meta(con, key, value):
    con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, str(value)))


def get_meta(con, key, default=None):
    r = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return r[0] if r else default
