"""Small Qt helpers."""


def safe_emit(signal, *args):
    """Emit from a worker thread; the receiving QObject may already be gone at shutdown."""
    try:
        signal.emit(*args)
    except RuntimeError:
        pass


def system_env():
    """Environment for programs outside QDStar (browser, service commands).

    The Linux builds (PyInstaller, AppImage) point LD_LIBRARY_PATH at the bundled
    libraries. A system program started with it loads QDStar's Qt instead of its
    own and dies at once, e.g. xdg-open/kde-open when opening a link.
    """
    import os
    env = dict(os.environ)
    original = env.pop("LD_LIBRARY_PATH_ORIG", None)   # saved by the PyInstaller bootloader
    if original:
        env["LD_LIBRARY_PATH"] = original
    else:
        env.pop("LD_LIBRARY_PATH", None)
    return env


def open_url(url):
    """Open a link in the system browser."""
    import subprocess
    import sys
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    if sys.platform.startswith("linux") and getattr(sys, "frozen", False):
        try:
            subprocess.Popen(["xdg-open", str(url)], env=system_env(), start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError:
            pass
    return QDesktopServices.openUrl(QUrl(str(url)))


def start_detached(program, args):
    """QProcess.startDetached with the system environment (see system_env)."""
    from PySide6.QtCore import QProcess, QProcessEnvironment
    process = QProcess()
    process.setProgram(program)
    process.setArguments(args)
    env = QProcessEnvironment()
    for key, value in system_env().items():
        env.insert(key, value)
    process.setProcessEnvironment(env)
    ok, _pid = process.startDetached()
    return ok
