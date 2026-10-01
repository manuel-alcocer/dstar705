"""In-app updates of the Windows installation made by the Inno Setup installer.

The new installer is downloaded to the temporary folder and started silently
once QDStar has closed: it replaces the program files and starts QDStar again.
The portable zip has no uninstaller next to qdstar.exe and is left to the user.
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .net import download as fetch

DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "QDStar-update"
# /RELAUNCH=1 is handled by packaging/qdstar.iss: start QDStar after a silent install
INSTALLER_ARGS = ["/SILENT", "/NORESTART", "/RELAUNCH=1"]


def installed():
    """True when this process runs from a folder set up by the installer."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return False
    return (Path(sys.executable).parent / "unins000.exe").exists()


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


def launch(path):
    """Start the installer at path as a process of its own."""
    env = dict(os.environ)
    # The installer starts QDStar again: it must not take this process for its parent
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(path), *INSTALLER_ARGS], env=env, creationflags=flags, close_fds=True,
                     cwd=str(Path(path).parent),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
