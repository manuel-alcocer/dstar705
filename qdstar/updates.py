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


def is_newer(candidate, current=__version__):
    return version_tuple(candidate) > version_tuple(current)


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
        if not version or not is_newer(version):
            safe_emit(self.up_to_date)
            return
        url = pick_asset(release.get("assets", [])) or page
        safe_emit(self.available, version, url, page, release.get("body") or "")
