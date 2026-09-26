import signal
import sys
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QTimer, QTranslator
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import config, i18n
from .mainwindow import MainWindow


def main():
    app = QApplication(sys.argv)
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
    window = MainWindow()
    window.show()
    # Close the radio session cleanly on Ctrl+C / SIGTERM: a session that is
    # not closed stays stuck in the IC-705 until it is power cycled.
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: window.close())
    wake = QTimer(interval=300)
    wake.timeout.connect(lambda: None)  # lets Python run signal handlers
    wake.start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
