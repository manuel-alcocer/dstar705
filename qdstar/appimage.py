"""Per-user installation and in-place updates of the Linux AppImage.

An AppImage is a single file the user downloads anywhere. Installing moves it to
~/.local/bin/QDStar.AppImage and adds a menu entry and an icon under
~/.local/share, the places desktops look at for the current user. Updates
download the new AppImage next to the running one and rename it over it: the
running copy keeps its open file, so QDStar can be restarted into the new one.
"""

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

from .net import download
from .qtutil import system_env

HOME = Path.home()
INSTALL_PATH = HOME / ".local" / "bin" / "QDStar.AppImage"
DESKTOP_FILE = HOME / ".local" / "share" / "applications" / "qdstar.desktop"
ICON_FILE = HOME / ".local" / "share" / "icons" / "hicolor" / "scalable" / "apps" / "qdstar.svg"
ICON_SOURCE = Path(__file__).with_name("icon.svg")

DESKTOP_ENTRY = """[Desktop Entry]
Type=Application
Name=QDStar
Comment=IC-705 D-STAR Terminal Mode controller and gateway
Exec="{exec}"
TryExec={exec}
Icon=qdstar
Terminal=false
Categories=HamRadio;Network;
StartupWMClass=qdstar
"""

# The AppImage this process runs from; follows it when installing moves it
_current = os.environ.get("APPIMAGE") or None


def current():
    """Path of the running AppImage, or None when not running from one."""
    return Path(_current) if _current else None


def installed():
    return INSTALL_PATH.exists() and DESKTOP_FILE.exists()


def running_installed():
    path = current()
    return bool(path) and INSTALL_PATH.exists() and path.resolve() == INSTALL_PATH.resolve()


def _refresh_menus():
    for cmd in (["update-desktop-database", str(DESKTOP_FILE.parent)],
                ["gtk-update-icon-cache", "-q", "-t", str(ICON_FILE.parents[2])]):
        try:
            subprocess.run(cmd, env=system_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=10, check=False)
        except (OSError, subprocess.SubprocessError):
            pass   # optional tools: menus pick the entry up anyway


def install():
    """Move the running AppImage to INSTALL_PATH and add the menu entry and icon."""
    global _current
    source = current()
    if source is None:
        raise OSError("not running from an AppImage")
    INSTALL_PATH.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != INSTALL_PATH.resolve():
        tmp = INSTALL_PATH.with_suffix(".part")
        shutil.copyfile(source, tmp)
        os.chmod(tmp, 0o755)
        os.replace(tmp, INSTALL_PATH)
        try:
            source.unlink()     # moved, not copied: one AppImage to keep up to date
        except OSError:
            pass
        _current = str(INSTALL_PATH)
    ICON_FILE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ICON_SOURCE, ICON_FILE)
    DESKTOP_FILE.parent.mkdir(parents=True, exist_ok=True)
    DESKTOP_FILE.write_text(DESKTOP_ENTRY.format(exec=INSTALL_PATH))
    _refresh_menus()


def uninstall():
    """Remove the installed AppImage, menu entry and icon (settings and data stay)."""
    for path in (DESKTOP_FILE, ICON_FILE, INSTALL_PATH):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    _refresh_menus()


def target_for(version):
    """Where an update to version goes: over the installed copy, else next to the running one."""
    path = current()
    if path is None or running_installed():
        return INSTALL_PATH
    old = path.name
    # QDStar-0.4.7-x86_64.AppImage -> QDStar-0.4.8-x86_64.AppImage
    parts = old.split("-")
    if len(parts) >= 3 and parts[0] == "QDStar":
        return path.with_name("-".join([parts[0], version] + parts[2:]))
    return path


def update(url, version, digest="", progress=None):
    """Download the new AppImage and put it in place of the running one; returns its path.

    digest: 'sha256:<hex>' from the GitHub release, checked when present.
    """
    target = target_for(version)
    tmp = target.with_name(target.name + ".part")
    try:
        sha = hashlib.sha256()
        download(url, tmp, progress=progress, hasher=sha)
        if digest.startswith("sha256:") and sha.hexdigest() != digest.split(":", 1)[1].lower():
            raise OSError("the downloaded file is damaged (SHA-256 mismatch)")
        os.chmod(tmp, 0o755)
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()
    path = current()
    if path is not None and path.resolve() != target.resolve() and not running_installed():
        try:
            path.unlink()   # the old version's file, now replaced by the new name
        except OSError:
            pass
    return target


def relaunch(path):
    """Start the AppImage at path as a new process with the system environment."""
    env = system_env()
    for key in ("APPIMAGE", "APPDIR", "ARGV0", "OWD"):
        env.pop(key, None)
    subprocess.Popen([str(path)], env=env, start_new_session=True, cwd=str(HOME),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
