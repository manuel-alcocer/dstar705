import signal
import sys
from pathlib import Path

from . import startup

startup.progress(1, "Loading Qt…")

from PySide6.QtCore import QLibraryInfo, QTimer, QTranslator  # noqa: E402
from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from . import config, i18n  # noqa: E402
from .i18n import tr  # noqa: E402


def main():
    app = QApplication(sys.argv)
    from .single import InstanceServer, ask_running_instance
    if ask_running_instance():
        startup.done()      # QDStar is already open: it has been brought to the front
        return 0
    instance = InstanceServer(app)
    app.setOrganizationName(config.ORG)
    app.setApplicationName(config.APP)
    app.setDesktopFileName("qdstar")
    app.setWindowIcon(QIcon(str(Path(__file__).with_name("icon.svg"))))
    config.migrate_legacy()
    language = i18n.set_language(config.get("ui/language"))
    # Qt's own buttons and dialogs in the same language
    translator = QTranslator(app)
    if language != "en" and translator.load(f"qtbase_{language}", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(translator)
    config.import_wfview_credentials()
    startup.progress(2, tr("Loading modules…"))
    from .mainwindow import MainWindow
    window = MainWindow()
    window.show()
    startup.done()

    instance.show_requested.connect(window.show_window)
    # Close the radio session cleanly on Ctrl+C / SIGTERM: a session that is
    # not closed stays stuck in the IC-705 until it is power cycled.
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: window.quit())
    wake = QTimer(interval=300)
    wake.timeout.connect(lambda: None)  # lets Python run signal handlers
    wake.start()
    code = app.exec()
    if window.relaunch_path:
        # Updated AppImage: start it once this instance no longer holds the single-instance socket
        instance.server.close()
        from . import appimage
        appimage.relaunch(window.relaunch_path)
    elif window.installer_path:
        # Downloaded Windows installer: it updates the files and starts QDStar again
        instance.server.close()
        from . import winupdate
        winupdate.launch(window.installer_path)
    return code


if __name__ == "__main__":
    sys.exit(main())
