import signal
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import config
from .mainwindow import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setOrganizationName(config.ORG)
    app.setApplicationName(config.APP)
    app.setDesktopFileName("dstar705")
    app.setWindowIcon(QIcon(str(Path(__file__).with_name("icon.svg"))))
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
