"""Operator name lookup (radioid.net), cached in SQLite, resolved in a worker thread."""

import json
import threading
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Signal

from .qtutil import safe_emit

RADIOID_URL = "https://radioid.net/api/dmr/user/?callsign={}"
USER_AGENT = "DStar705/0.2 (+https://github.com/manuel-alcocer/dstar705)"


class NameLookup(QObject):
    resolved = Signal(str, str, str)  # callsign, name, location

    def __init__(self, storage):
        super().__init__()
        self.storage = storage
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="lookup")
        self.pending = set()
        self.lock = threading.Lock()

    def request(self, callsign):
        callsign = callsign.split()[0].upper() if callsign.strip() else ""
        if not callsign:
            return
        cached = self.storage.cached_name(callsign)
        if cached:
            self.resolved.emit(callsign, cached["name"] or "", cached["location"] or "")
            return
        with self.lock:
            if callsign in self.pending:
                return
            self.pending.add(callsign)
        self.pool.submit(self._fetch, callsign)

    def _fetch(self, callsign):
        name = location = ""
        ok = False
        try:
            req = urllib.request.Request(RADIOID_URL.format(urllib.parse.quote(callsign)),
                                         headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read(200_000))
            ok = True
            results = [r for r in data.get("results", []) if r.get("callsign", "").upper() == callsign]
            if results:
                r = results[0]
                name = " ".join(p for p in (r.get("fname") or r.get("name"), r.get("surname")) if p).strip()
                location = ", ".join(p for p in (r.get("city"), r.get("country")) if p)
        except (OSError, ValueError):
            pass
        finally:
            with self.lock:
                self.pending.discard(callsign)
        if ok:
            self.storage.store_name(callsign, name, location)
        safe_emit(self.resolved, callsign, name, location)
