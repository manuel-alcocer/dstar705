"""In-app updates of the Windows installation made by the Inno Setup installer.

The new installer is downloaded to the temporary folder and started silently
once QDStar has closed: it replaces the program files and starts QDStar again.
The same installer moves the installation between "only for me" and "all users".
The portable zip has no uninstaller next to qdstar.exe and is left to the user.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import __version__
from .net import download as fetch
from .net import http_get
from .updates import version_key

DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "QDStar-update"
RELEASES_API = "https://api.github.com/repos/manuel-alcocer/qdstar/releases/"
INSTALLER_SUFFIX = "-windows-x64-setup.exe"
# Same AppId as packaging/qdstar.iss
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{7C2E3B0A-6F4D-4B1B-9E0A-D57A705D57A7}_is1"
# /RELAUNCH=1 is handled by packaging/qdstar.iss: start QDStar after a silent install
INSTALLER_ARGS = ["/SILENT", "/NORESTART", "/RELAUNCH=1"]


def installed():
    """True when this process runs from a folder set up by the installer."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return False
    return (Path(sys.executable).parent / "unins000.exe").exists()


def per_user():
    """True when this installation is the current user's own, False when it is for all users."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
            location = winreg.QueryValueEx(key, "InstallLocation")[0]
    except OSError:
        return False
    here = str(Path(sys.executable).parent)
    return os.path.normcase(os.path.normpath(location)) == os.path.normcase(os.path.normpath(here))


def switch_args(all_users, language):
    """Installer arguments that move this installation to all users, or to the current one only."""
    return [f"/SWITCHMODE={'allusers' if all_users else 'currentuser'}",
            f"/LANG={'spanish' if language == 'es' else 'english'}", "/NORESTART"]


def find_installer(version=__version__):
    """(version, download URL, digest) of the installer of version; of the latest release
    when that version is not published (a development build, a release deleted since)."""
    for name in ("tags/" + version.split("+", 1)[0], "latest"):
        try:
            release = json.loads(http_get(RELEASES_API + name, timeout=15, limit=1_000_000))
        except (OSError, ValueError):
            continue
        found = release.get("tag_name", "")
        if version_key(found) < version_key(version):
            continue    # never back to an older version (it may not know /SWITCHMODE either)
        for asset in release.get("assets", []):
            if asset.get("name", "").endswith(INSTALLER_SUFFIX):
                return found, asset.get("browser_download_url", ""), asset.get("digest") or ""
    raise OSError("the installer of this version was not found on GitHub")


def download_current(progress=None):
    """Download the installer of the running version; returns its path."""
    version, url, digest = find_installer()
    return download(url, version, digest, progress)


def cleanup():
    """Remove installers left by earlier updates."""
    shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)


def download(url, version, digest="", progress=None):
    """Download the installer of version; returns its path.

    digest: 'sha256:<hex>' from the GitHub release, checked when present.
    """
    cleanup()
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = DOWNLOAD_DIR / f"QDStar-{version}-windows-x64-setup.exe"
    tmp = target.with_name(target.name + ".part")
    try:
        sha = hashlib.sha256()
        fetch(url, tmp, progress=progress, hasher=sha)
        if digest.startswith("sha256:") and sha.hexdigest() != digest.split(":", 1)[1].lower():
            raise OSError("the downloaded file is damaged (SHA-256 mismatch)")
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()
    return target


def launch(path, args=INSTALLER_ARGS, restart_if_unchanged=False):
    """Start the installer at path as a process of its own.

    restart_if_unchanged: start this QDStar again when the installer ends and it is still
    there (a declined UAC prompt, an error), for runs where the installer only starts the
    copy it installs.
    """
    env = dict(os.environ)
    # The installer starts QDStar again: it must not take this process for its parent
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    command = [str(path), *args]
    flags = getattr(subprocess, "DETACHED_PROCESS", 0)
    if restart_if_unchanged:
        exe = sys.executable
        command = f'cmd.exe /c ""{path}" {" ".join(args)} & if exist "{exe}" start "" "{exe}""'
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(command, env=env, creationflags=flags | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                     close_fds=True, cwd=str(Path(path).parent),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
