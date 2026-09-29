"""Reflector registry (JSON) and background status polling."""

import html
import json
import re
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Signal

from . import config
from .net import http_get
from .qtutil import safe_emit
from .i18n import tr

XLX_API_URL = "http://xlxapi.rlx.lu/api.php?do=GetReflectorList"
XLX_API_REFRESH = 600
STATUS_REFRESH = 30
ONLINE_MAX_AGE = 3600
MODULE_ROW_RE = re.compile(r"\|\s*([A-Z])\s*\|\s*([^|]*?)\s*\|\s*(\d+)\s*\|\s*REF\d{3}\1L", re.I)

FIELDS = ("via", "to", "server", "name", "description", "notes", "dashboard", "api")


def normalize_to(text, via="int"):
    """INT: '/xlx214d' -> '/XLX214D' (TO written to the radio).
    EXT: 'ref001c' -> 'REF001 C' (reflector linked by ircDDBGateway)."""
    text = re.sub(r"\s+", "", str(text).upper())
    if via == "ext":
        text = text.lstrip("/")
        if not re.fullmatch(r"[A-Z0-9]{4,7}[A-Z]", text):
            raise ValueError(tr("Invalid reflector format (e.g. REF001 C)"))
        return text[:-1].ljust(7) + text[-1]
    if not text.startswith("/"):
        text = "/" + text
    if not re.fullmatch(r"/[A-Z0-9]{3,6}[A-Z]", text):
        raise ValueError(tr("Invalid TO format (e.g. /XLX214D)"))
    return text


def split_to(to):
    """'/XLX214D' or 'XLX214 D' -> ('XLX214', 'D')."""
    return to.lstrip("/")[:-1].strip(), to[-1]


class Registry(QObject):
    """The user's own reflectors (reflectors.json, editable) plus the enabled sources
    (sources.py: built into QDStar, URL, file, git), read only. When a reflector is in
    several places, the user's own copy wins, then the sources in their order."""

    changed = Signal()

    def __init__(self):
        super().__init__()
        from .sources import BUILTIN_ID, SourceManager
        self.path = config.data_dir() / "reflectors.json"
        self.lock = threading.Lock()
        self.sources = SourceManager(self._clean)
        self.sources.updated.connect(self.changed)
        self.items = self._load(BUILTIN_ID)

    def _load(self, builtin_id):
        try:
            items = json.loads(self.path.read_text())
        except (OSError, ValueError):
            items = []           # the shipped list comes from the built-in source
        items = [self._clean(i) for i in items if isinstance(i, dict) and i.get("to")]
        if not config.get("reflectors/sources_migrated"):
            # Up to 0.7 the shipped list was copied here on first run: keep only what the user
            # added or changed, the rest now comes (and gets updated) from the built-in source
            builtin = self.sources.source_items(builtin_id)
            items = [i for i in items if i not in builtin]
            config.put("reflectors/sources_migrated", True)
        self._save(items)
        return items

    @staticmethod
    def _clean(item):
        clean = {f: str(item.get(f, "") or "").strip() for f in FIELDS}
        if clean["via"] not in ("int", "ext"):
            clean["via"] = "int" if clean["to"].startswith("/") else "ext"
        clean["to"] = normalize_to(clean["to"], clean["via"])
        if clean["via"] == "ext":
            clean["server"] = ""
        return clean

    def _save(self, items):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False))
        tmp.replace(self.path)

    def _merged(self):
        """Every reflector once, with 'source' (id, '' = the user's list) and 'origin' (name)."""
        from .sources import display_name
        with self.lock:
            merged = [dict(i, source="", origin="") for i in self.items]
        seen = {i["to"] for i in merged}
        for source in self.sources.enabled():
            for item in self.sources.source_items(source["id"]):
                if item["to"] not in seen:
                    seen.add(item["to"])
                    merged.append(dict(item, source=source["id"], origin=display_name(source)))
        return merged

    def list(self, via=None):
        return [i for i in self._merged() if via is None or i["via"] == via]

    def get(self, to):
        return next((i for i in self._merged() if i["to"] == to), None)

    def local(self):
        """The user's own reflectors, as saved (for exporting)."""
        with self.lock:
            return [dict(i) for i in self.items]

    def upsert(self, item, old_to=None):
        item = self._clean(item)
        with self.lock:
            key = old_to or item["to"]
            for i, existing in enumerate(self.items):
                if existing["to"] == key:
                    self.items[i] = item
                    break
            else:
                self.items.append(item)
            self._save(self.items)
        self.changed.emit()
        return item

    def delete(self, to):
        with self.lock:
            self.items = [i for i in self.items if i["to"] != to]
            self._save(self.items)
        self.changed.emit()


def _fetch(url, limit=2_000_000):
    return http_get(url, limit=limit)


def _page_text(raw):
    raw = re.sub(r"(?s)<(script|style).*?</\1>", "", raw)
    text = html.unescape(re.sub(r"<[^>]+>", " | ", raw))
    return re.sub(r"\s+", " ", re.sub(r"(\s*\|\s*)+", " | ", text))


class StatusPoller(QObject):
    """Checks every registered reflector; emits status dicts keyed by TO."""

    status = Signal(str, dict)
    internet = Signal(bool)

    def __init__(self, registry, terminal_call_getter):
        super().__init__()
        self.registry = registry
        self.terminal_call = terminal_call_getter  # e.g. 'N0CALL Z' (R1 in terminal mode)
        self.xlx = {}
        self.xlx_fetched = 0.0
        self.wakeup = threading.Event()
        self.stopping = False
        self.thread = threading.Thread(target=self._run, daemon=True, name="reflector-status")

    def start(self):
        self.thread.start()

    def refresh_now(self):
        self.wakeup.set()

    def stop(self):
        self.stopping = True
        self.wakeup.set()

    def _refresh_xlx(self):
        if time.time() - self.xlx_fetched < XLX_API_REFRESH:
            return True
        try:
            xml = _fetch(XLX_API_URL)
        except OSError:
            return False
        found = {}
        for block in re.findall(r"<reflector>(.*?)</reflector>", xml, re.S):
            fields = dict(re.findall(r"<(\w+)>(.*?)</\1>", block, re.S))
            name = fields.get("name", "").strip().upper()
            if name:
                found[name] = {
                    "dashboard": html.unescape(fields.get("dashboardurl", "").strip()),
                    "lastcontact": int(fields.get("lastcontact", "0") or 0),
                    "comment": html.unescape(fields.get("comment", "").strip()),
                    "country": html.unescape(fields.get("country", "").strip()),
                }
        if found:
            self.xlx = found
            self.xlx_fetched = time.time()
        return True

    def _terminal_regex(self):
        call = (self.terminal_call() or "").strip()
        if not call:
            return None
        base, _, suffix = call.partition(" ")
        suffix = suffix.strip()
        pattern = re.escape(base) + (r"[\s\-]*" + re.escape(suffix) if suffix else "")
        return re.compile(r"\b" + pattern + r"\b", re.I)

    def _check(self, item):
        reflector, module = split_to(item["to"])
        # DCS/XRF reflectors usually share their number with an XLX; REF numbers do not
        number = reflector[3:]
        xlx = self.xlx.get(reflector) or ({} if reflector.startswith("REF") else self.xlx.get("XLX" + number, {}))
        dashboard = item.get("dashboard") or xlx.get("dashboard", "")
        result = {
            "online": None, "users": None, "module_name": "", "linked": None,
            "heard": [], "nodes": [], "comment": xlx.get("comment", ""), "country": xlx.get("country", ""),
            "dashboard": dashboard, "checked": time.time(),
        }
        if xlx:
            result["online"] = time.time() - xlx["lastcontact"] < ONLINE_MAX_AGE
        # EXT links are reported by ircDDBGateway itself
        term_re = self._terminal_regex() if item["via"] == "int" else None

        api = item.get("api")
        if api:
            try:
                users = json.loads(_fetch(api + "?api=users"))
                nodes = [u for u in users if u.get("module") == module]
                result["online"] = True
                result["users"] = len(nodes)
                result["nodes"] = [u.get("callsign", "").strip() for u in nodes]
                if term_re:
                    result["linked"] = any(term_re.search(u.get("callsign", "")) for u in users)
                heard = json.loads(_fetch(api + "?api=heard"))
                result["heard"] = [
                    {"callsign": h.get("callsign", ""), "name": h.get("name", ""),
                     "via": h.get("via", ""), "time": h.get("time", "")}
                    for h in heard[:8]
                ]
            except (OSError, ValueError):
                pass
        if dashboard and result["users"] is None:
            base = dashboard.rstrip("/") + "/"
            for page in ("index.php?show=modules", "modules.php"):
                try:
                    text = _page_text(_fetch(urllib.parse.urljoin(base, page)))
                except OSError:
                    continue
                rows = MODULE_ROW_RE.findall(text)
                if rows:
                    result["online"] = True
                    for mod, name, users in rows:
                        if mod.upper() == module:
                            result["users"] = int(users)
                            result["module_name"] = name.strip(" -")
                    break
            if term_re and result["linked"] is None:
                try:
                    text = _page_text(_fetch(urllib.parse.urljoin(base, "index.php?show=repeaters")))
                    result["linked"] = bool(term_re.search(text))
                except OSError:
                    pass
        return item["to"], result

    def _run(self):
        while not self.stopping:
            safe_emit(self.internet, self._refresh_xlx())
            items = self.registry.list()
            if items:
                with ThreadPoolExecutor(max_workers=4) as pool:
                    for to, result in pool.map(self._check, items):
                        if self.stopping:
                            return
                        safe_emit(self.status, to, result)
            self.wakeup.wait(STATUS_REFRESH)
            self.wakeup.clear()
