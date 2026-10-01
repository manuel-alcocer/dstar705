"""New version check against the project's GitHub releases."""

import json
import os
import platform
import sys
import threading

from PySide6.QtCore import QObject, Signal

from . import __version__
from .net import http_get
from .qtutil import safe_emit

LATEST_RELEASE_API = "https://api.github.com/repos/manuel-alcocer/qdstar/releases/latest"


def version_tuple(text):
    """'0.3.2' -> (0, 3, 2); anything after the numbers (e.g. '~dev5') is ignored."""
    parts = []
    for piece in text.strip().lstrip("vV").split("."):
        digits = ""
        for ch in piece:
            if not ch.isdigit():
                break
            digits += ch
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def version_key(text):
    """Sort key that follows semantic versioning: 0.9.0-beta.2 < 0.9.0-rc.1 < 0.9.0.

    Build metadata ('+…') does not count; the '~dev5' of old CI builds is a pre-release.
    """
    text = text.strip().lstrip("vV").split("+", 1)[0]
    cut = min((text.index(mark) for mark in "-~" if mark in text), default=None)
    numbers = version_tuple(text[:cut])
    if cut is None:
        return numbers, 1, ()
    # Numeric identifiers sort before the others and by value, as semver says
    parts = tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in text[cut + 1:].split("."))
    return numbers, 0, parts


def is_newer(candidate, current=__version__):
    return version_key(candidate) > version_key(current)


def pick_asset(assets):
    """Download URL of the release file that suits this installation, or None."""
    machine = platform.machine().lower()
    arm = machine in ("aarch64", "arm64")
    names = {a.get("name", ""): a.get("browser_download_url", "") for a in assets}

    def find(*suffixes):
        for name, url in names.items():
            if name.endswith(suffixes):
                return url
        return None

    if sys.platform == "win32":
        return find("-windows-x64-setup.exe")
    if sys.platform.startswith("linux"):
        if os.environ.get("APPIMAGE"):
            return find("-aarch64.AppImage" if arm else "-x86_64.AppImage")
        if getattr(sys, "frozen", False) and sys.executable.startswith("/opt/qdstar"):
            return find("_arm64.deb" if arm else "_amd64.deb")
        if getattr(sys, "frozen", False):
            return find("-linux-arm64.tar.gz" if arm else "-linux-amd64.tar.gz")
    return None   # running from source: the release page is the right place


class UpdateChecker(QObject):
    # version, download URL (asset or release page), release page URL, release notes
    available = Signal(str, str, str, str)
    up_to_date = Signal()
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.digests = {}    # download URL -> 'sha256:<hex>' published by GitHub

    def check(self):
        threading.Thread(target=self._run, daemon=True, name="update-check").start()

    def _run(self):
        try:
            release = json.loads(http_get(LATEST_RELEASE_API, timeout=15, limit=1_000_000))
        except (OSError, ValueError) as exc:
            safe_emit(self.failed, str(exc))
            return
        version = release.get("tag_name", "")
        page = release.get("html_url", "")
        # GitHub's "latest" is never a pre-release; a beta or rc that got there by
        # mistake (published without the pre-release mark) is not offered either
        prerelease = release.get("prerelease") or (version and not version_key(version)[1])
        if not version or prerelease or not is_newer(version):
            safe_emit(self.up_to_date)
            return
        assets = release.get("assets", [])
        self.digests = {x.get("browser_download_url", ""): x.get("digest") or "" for x in assets}
        url = pick_asset(assets) or page
        safe_emit(self.available, version, url, page, release.get("body") or "")


class UpdateDownload(QObject):
    """Downloads a new version in the background.

    fetch(url, version, digest, progress=) does the work and returns the path of
    the result: appimage.update (the new AppImage, already in place of the running
    one) or winupdate.download (the Windows installer, still to be run).
    """
    progress = Signal(int, int)      # bytes done, total (0 = unknown)
    finished = Signal(str)           # path of the downloaded file
    failed = Signal(str)

    def __init__(self, fetch, parent=None):
        super().__init__(parent)
        self.fetch = fetch

    def start(self, url, version, digest=""):
        threading.Thread(target=self._run, args=(url, version, digest), daemon=True,
                         name="update-download").start()

    def _run(self, url, version, digest):
        try:
            path = self.fetch(url, version, digest, progress=lambda d, t: safe_emit(self.progress, d, t))
        except OSError as exc:
            safe_emit(self.failed, str(exc))
            return
        safe_emit(self.finished, str(path))
