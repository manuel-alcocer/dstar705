"""SQLite storage: conversation history and callsign name cache."""

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
CREATE TABLE IF NOT EXISTS names (
    callsign TEXT PRIMARY KEY,
    name TEXT,
    location TEXT,
    fetched REAL NOT NULL
);
"""


class Storage:
    def __init__(self, path=None):
        self.path = path or config.data_dir() / "dstar705.db"
        self.lock = threading.Lock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

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

    def recent(self, limit=500):
        with self.lock:
            rows = self.db.execute("SELECT * FROM history ORDER BY started DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def last_rx(self, reflector, limit=4):
        """Most recent RX entries heard on one reflector."""
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM history WHERE direction = 'RX' AND reflector = ? ORDER BY started DESC LIMIT ?",
                (reflector, limit)).fetchall()
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
