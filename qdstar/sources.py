"""Where reflector lists come from, besides the user's own list: the list built into QDStar,
a URL, a local file or a git repository (read only). Each source is cached, so the last good
copy is used without a connection.

A source is a dict: id, type (builtin/url/file/git), name, enabled, location (URL, path or
repository), and for git: branch and path (the file inside the repository), username.
The git password or token lives in the system keyring (credentials.py), never in the settings,
the command line or the log.
"""

import json
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from . import config, credentials
from .i18n import N_, tr
from .net import http_get
from .qtutil import safe_emit, system_env

BUILTIN_ID = "builtin"
DEFAULT_REFLECTORS = Path(__file__).with_name("default_reflectors.json")
TYPES = {"url": N_("URL"), "file": N_("File"), "git": N_("Git repository")}
REFRESH_EVERY = 6 * 3600          # s, URL and git sources
GIT_TIMEOUT = 90                  # s per git command
MAX_SIZE = 2_000_000              # bytes of JSON accepted from a source


class SourceError(Exception):
    pass


def default_sources():
    return [{"id": BUILTIN_ID, "type": "builtin", "name": "", "enabled": True}]


def load_sources():
    try:
        sources = json.loads(config.get("reflectors/sources") or "[]")
    except ValueError:
        sources = []
    sources = [s for s in sources if isinstance(s, dict) and s.get("id") and s.get("type")]
    if not any(s["id"] == BUILTIN_ID for s in sources):
        sources = default_sources() + sources
    return sources


def save_sources(sources):
    config.put("reflectors/sources", json.dumps(sources, ensure_ascii=False))


def new_source(kind):
    return {"id": uuid.uuid4().hex[:12], "type": kind, "name": "", "enabled": True, "location": "",
            "branch": "", "path": "reflectors.json", "username": ""}


def display_name(source):
    if source["type"] == "builtin":
        return tr("Built into QDStar")
    return source.get("name") or source.get("location") or tr(TYPES.get(source["type"], source["type"]))


def secret_key(source):
    return f"reflector-source-{source['id']}"


def parse(text, origin):
    """The JSON of a reflector list: a list of reflector objects (as default_reflectors.json)."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise SourceError(tr("{origin} is not valid JSON: {error}", origin=origin, error=exc)) from None
    if isinstance(data, dict):
        data = data.get("reflectors")      # also accept {"reflectors": [...]}
    if not isinstance(data, list):
        raise SourceError(tr("{origin} does not contain a list of reflectors", origin=origin))
    return [item for item in data if isinstance(item, dict)]


# --- fetching (worker thread) -------------------------------------------------------------

def _no_window():
    return {"creationflags": 0x08000000} if sys.platform == "win32" else {}   # CREATE_NO_WINDOW


def _git(args, cwd=None, env=None):
    try:
        result = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True,
                                timeout=GIT_TIMEOUT, **_no_window())
    except FileNotFoundError:
        raise SourceError(tr("git is not installed (it is needed for git repositories)")) from None
    except subprocess.TimeoutExpired:
        raise SourceError(tr("git did not finish in {seconds} s", seconds=GIT_TIMEOUT)) from None
    if result.returncode != 0:
        lines = [l for l in (result.stderr or result.stdout).strip().splitlines() if l.strip()]
        raise SourceError(tr("git: {error}", error=lines[-1] if lines else result.returncode))
    return result.stdout


def _git_env(source):
    """Credentials reach git through the environment and a one-off credential helper, so they
    never appear on the command line (ps) nor get stored by the user's own helpers."""
    # system_env(): the Linux builds point LD_LIBRARY_PATH at their own libraries, which
    # break system programs such as git and ssh
    env = dict(system_env(), GIT_TERMINAL_PROMPT="0", GIT_SSH_COMMAND="ssh -o BatchMode=yes")
    args = []
    secret = credentials.load(secret_key(source))
    if secret:
        env["QDSTAR_GIT_USER"] = source.get("username") or "git"
        env["QDSTAR_GIT_PASS"] = secret
        args = ["-c", "credential.helper=",
                "-c", 'credential.helper=!f() { echo "username=${QDSTAR_GIT_USER}"; '
                      'echo "password=${QDSTAR_GIT_PASS}"; }; f']
    return env, args


def fetch_git(source, cache_dir):
    repo = source.get("location", "").strip()
    if not repo:
        raise SourceError(tr("No repository given"))
    work = cache_dir / f"{source['id']}.git"
    env, cred = _git_env(source)
    branch = source.get("branch", "").strip()
    if (work / ".git").is_dir():
        _git([*cred, "-C", str(work), "remote", "set-url", "origin", repo], env=env)
        _git([*cred, "-C", str(work), "fetch", "--depth", "1", "origin", branch or "HEAD"], env=env)
        _git(["-C", str(work), "reset", "--hard", "--quiet", "FETCH_HEAD"], env=env)
    else:
        shutil.rmtree(work, ignore_errors=True)
        _git([*cred, "clone", "--depth", "1", "--quiet", *(["--branch", branch] if branch else []), repo, str(work)],
             env=env)
    path = (source.get("path") or "reflectors.json").strip().lstrip("/")
    target = (work / path).resolve()
    if work.resolve() not in target.parents:
        raise SourceError(tr("The path must be inside the repository"))
    try:
        return target.read_text(encoding="utf-8")
    except OSError:
        raise SourceError(tr("{path} is not in the repository", path=path)) from None


def fetch(source, cache_dir):
    """The raw JSON text of a source. Raises SourceError with a message for the user."""
    kind = source["type"]
    if kind == "builtin":
        return DEFAULT_REFLECTORS.read_text(encoding="utf-8")
    location = source.get("location", "").strip()
    if kind == "url":
        if not location.startswith(("http://", "https://")):
            raise SourceError(tr("The URL must start with http:// or https://"))
        try:
            return http_get(location, limit=MAX_SIZE)
        except OSError as exc:
            raise SourceError(tr("Could not download it: {error}", error=exc)) from None
    if kind == "file":
        try:
            return Path(location).expanduser().read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise SourceError(tr("Could not read it: {error}", error=exc)) from None
    if kind == "git":
        return fetch_git(source, cache_dir)
    raise SourceError(tr("Unknown source type {type}", type=kind))


class SourceManager(QObject):
    """Fetches the enabled sources in the background and keeps their last good copies."""

    updated = Signal()                    # the items of some source changed
    status_changed = Signal(str)          # source id
    _done = Signal(str, object, str)      # id, raw items or None, error (from the worker thread)

    def __init__(self, clean):
        """clean: validates and normalises one reflector dict (raises ValueError)."""
        super().__init__()
        self.clean = clean
        self.cache_dir = config.data_dir() / "sources"
        self.cache_dir.mkdir(exist_ok=True)
        self.items = {}                   # source id -> [clean reflector dicts]
        self.status = {}                  # source id -> {"ok", "when", "message", "count"}
        self.busy = set()
        self.lock = threading.Lock()
        self._done.connect(self._finished)
        self.timer = QTimer(self, interval=REFRESH_EVERY * 1000)
        self.timer.timeout.connect(lambda: self.refresh(remote_only=True))
        for source in load_sources():
            self._load_cached(source)
        self.timer.start()

    # --- public ---------------------------------------------------------------

    def sources(self):
        return load_sources()

    def enabled(self):
        return [s for s in load_sources() if s.get("enabled", True)]

    def set_sources(self, sources):
        save_sources(sources)
        ids = {s["id"] for s in sources}
        for stale in set(self.items) - ids:
            self.items.pop(stale, None)
            self.status.pop(stale, None)
            (self.cache_dir / f"{stale}.json").unlink(missing_ok=True)
            shutil.rmtree(self.cache_dir / f"{stale}.git", ignore_errors=True)
            credentials.store(f"reflector-source-{stale}", "")
        self.updated.emit()

    def refresh(self, source_id=None, remote_only=False):
        """Fetch one source, or every enabled one, in a worker thread."""
        for source in self.enabled():
            if source_id and source["id"] != source_id:
                continue
            if remote_only and source["type"] not in ("url", "git"):
                continue
            if source["id"] in self.busy:
                continue
            self.busy.add(source["id"])
            threading.Thread(target=self._fetch, args=(dict(source),), daemon=True,
                             name=f"source-{source['id']}").start()

    # --- internals ---------------------------------------------------------------

    def _load_cached(self, source):
        if source["type"] == "builtin":
            self._apply(source["id"], self._parse(DEFAULT_REFLECTORS.read_text(encoding="utf-8"), source), "")
            return
        path = self.cache_dir / f"{source['id']}.json"
        if path.exists():
            try:
                raw = parse(path.read_text(encoding="utf-8"), display_name(source))
                self._apply(source["id"], raw, "", when=path.stat().st_mtime, fetched=False)
            except (OSError, SourceError):
                pass

    def _parse(self, text, source):
        return parse(text, display_name(source))

    def _fetch(self, source):
        try:
            text = fetch(source, self.cache_dir)
            raw = parse(text, display_name(source))
            if source["type"] != "builtin":
                tmp = self.cache_dir / f"{source['id']}.tmp"
                tmp.write_text(text, encoding="utf-8")
                tmp.replace(self.cache_dir / f"{source['id']}.json")
            safe_emit(self._done, source["id"], raw, "")
        except SourceError as exc:
            safe_emit(self._done, source["id"], None, str(exc))
        except Exception as exc:          # never let a worker die silently
            safe_emit(self._done, source["id"], None, str(exc))

    def _finished(self, source_id, raw, error):
        self.busy.discard(source_id)
        if raw is None:
            previous = self.status.get(source_id, {})
            self.status[source_id] = dict(previous, ok=False, message=error, when=time.time())
            self.status_changed.emit(source_id)
            return
        self._apply(source_id, raw, "")
        self.updated.emit()

    def _apply(self, source_id, raw, error, when=None, fetched=True):
        items, skipped = [], 0
        for item in raw:
            try:
                items.append(self.clean(item))
            except (ValueError, KeyError, TypeError):
                skipped += 1
        with self.lock:
            self.items[source_id] = items
        message = tr("{n} skipped (invalid)", n=skipped) if skipped else ""
        self.status[source_id] = {"ok": True, "when": when or time.time(), "message": message,
                                  "count": len(items), "fetched": fetched}
        self.status_changed.emit(source_id)

    def source_items(self, source_id):
        with self.lock:
            return [dict(i) for i in self.items.get(source_id, [])]
