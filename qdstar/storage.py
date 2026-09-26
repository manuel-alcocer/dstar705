"""SQLite storage: conversation history and callsign name cache."""

import json
import sqlite3
import threading
import time

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started REAL NOT NULL,
    ended REAL,
    direction TEXT NOT NULL,          -- RX or TX
    callsign TEXT NOT NULL,
    suffix TEXT,
    name TEXT,
    location TEXT,
    reflector TEXT,                   -- TO in use, e.g. /XLX214D
    message TEXT,
    rpt1 TEXT,
    rpt2 TEXT
);
CREATE INDEX IF NOT EXISTS history_started ON history(started);
CREATE TABLE IF NOT EXISTS dprs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    received REAL NOT NULL,
    name TEXT NOT NULL,               -- station, object or item name (e.g. EB2EMZ-W)
    kind TEXT NOT NULL,               -- position, object, item, weather
    symbol TEXT,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    via TEXT,                         -- station whose over carried it (e.g. ED2YAV)
    reflector TEXT,
    weather TEXT                      -- JSON with the weather fields
);
CREATE INDEX IF NOT EXISTS dprs_received ON dprs(received);
CREATE TABLE IF NOT EXISTS names (
    callsign TEXT PRIMARY KEY,
    name TEXT,
    location TEXT,
    fetched REAL NOT NULL
);
"""


class Storage:
    def __init__(self, path=None):
        self.path = path or config.data_dir() / "qdstar.db"
        self.lock = threading.Lock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(history)")}
        for column in ("lat", "lon"):          # added in 0.3.0 (D-PRS positions)
            if column not in columns:
                self.db.execute(f"ALTER TABLE history ADD COLUMN {column} REAL")
        # 0.3.2-0.3.4 could store 0°,0° (a radio without GPS fix): that is no position
        self.db.execute("UPDATE history SET lat = NULL, lon = NULL WHERE lat = 0 AND lon = 0")
        self.db.commit()

    # --- history -------------------------------------------------------

    def start_entry(self, direction, callsign, suffix="", reflector="", rpt1="", rpt2="", started=None):
        with self.lock, self.db:
            cur = self.db.execute(
                "INSERT INTO history (started, direction, callsign, suffix, reflector, rpt1, rpt2)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (started or time.time(), direction, callsign, suffix, reflector, rpt1, rpt2),
            )
            return cur.lastrowid

    def update_entry(self, entry_id, **fields):
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self.lock, self.db:
            self.db.execute(f"UPDATE history SET {cols} WHERE id = ?", (*fields.values(), entry_id))

    def fill_recent(self, callsign, field, value, window=900):
        """Set a field on this station's recent entries that still lack it (late name/message)."""
        if not value:
            return 0
        since = time.time() - window
        with self.lock, self.db:
            cur = self.db.execute(
                f"UPDATE history SET {field} = ? WHERE callsign = ? AND started >= ?"
                f" AND ({field} IS NULL OR {field} = '')", (value, callsign, since))
            return cur.rowcount

    def recent(self, limit=500):
        with self.lock:
            rows = self.db.execute("SELECT * FROM history ORDER BY started DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def last_heard(self, reflector, limit=4):
        """Most recent overs on one reflector, received or our own transmissions."""
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM history WHERE reflector = ? ORDER BY started DESC LIMIT ?",
                (reflector, limit)).fetchall()
        return [dict(r) for r in rows]

    def last_position(self, callsign, max_age=6 * 3600):
        """Most recent D-PRS position stored for a station, or None."""
        with self.lock:
            row = self.db.execute(
                "SELECT lat, lon FROM history WHERE callsign = ? AND lat IS NOT NULL AND started >= ?"
                " ORDER BY started DESC LIMIT 1", (callsign, time.time() - max_age)).fetchone()
        return (row["lat"], row["lon"]) if row else None

    def clear_via(self, callsign):
        """Remove a wrongly assigned relaying station (0.4.0-0.4.2 could use our own call sign)."""
        with self.lock, self.db:
            self.db.execute("UPDATE dprs SET via = '' WHERE via = ?", (callsign,))

    def add_dprs(self, pos, via, reflector):
        """Store a received D-PRS report, unless the same one arrived in the last 10 minutes."""
        with self.lock, self.db:
            dup = self.db.execute(
                "SELECT id FROM dprs WHERE name = ? AND kind = ? AND lat = ? AND lon = ? AND received >= ?",
                (pos.callsign, pos.kind, pos.lat, pos.lon, time.time() - 600)).fetchone()
            if dup:
                return False
            self.db.execute(
                "INSERT INTO dprs (received, name, kind, symbol, lat, lon, via, reflector, weather)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (time.time(), pos.callsign, pos.kind, pos.symbol, pos.lat, pos.lon, via, reflector,
                 json.dumps(pos.weather) if pos.weather else None))
            return True

    def latest_weather(self, max_age=24 * 3600):
        """Latest weather report of each station received in the last max_age seconds."""
        with self.lock:
            rows = self.db.execute(
                "SELECT d.* FROM dprs d JOIN (SELECT name, MAX(received) AS latest FROM dprs"
                " WHERE kind = 'weather' AND received >= ? GROUP BY name) l"
                " ON d.name = l.name AND d.received = l.latest WHERE d.kind = 'weather'",
                (time.time() - max_age,)).fetchall()
        return [dict(r) for r in rows]

    def recent_dprs(self, limit=300):
        with self.lock:
            rows = self.db.execute("SELECT * FROM dprs ORDER BY received DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def clear_history(self):
        with self.lock, self.db:
            self.db.execute("DELETE FROM history")

    # --- names ---------------------------------------------------------

    def cached_name(self, callsign, max_age=30 * 86400):
        with self.lock:
            row = self.db.execute("SELECT * FROM names WHERE callsign = ?", (callsign,)).fetchone()
        if row and time.time() - row["fetched"] < max_age:
            return dict(row)
        return None

    def store_name(self, callsign, name, location):
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO names (callsign, name, location, fetched) VALUES (?, ?, ?, ?)",
                (callsign, name, location, time.time()),
            )
