"""Headless start-up test: build the main window in both modes, parse CI-V frames, check the CRC."""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QStandardPaths, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

QStandardPaths.setTestModeEnabled(True)


def main():
    app = QApplication(sys.argv)
    app.setOrganizationName("DStar705test")
    app.setApplicationName("DStar705test")

    from dstar705 import civ, config
    from dstar705.dstar.protocol import Header, ccitt_crc
    from dstar705.mainwindow import MainWindow

    # CI-V: MY call sign reply
    body = civ.FrameSplitter().feed(b"\xfe\xfe\xe0\xa4\x1f\x00N0CALL      \xfd")[0]
    assert civ.parse(body) == ("my_call", ("N0CALL", "")), civ.parse(body)
    # D-STAR header CRC (CRC-16/X.25 check value of "123456789" is 0x906E)
    assert ccitt_crc(b"123456789") == bytes([0x6E, 0x90])
    h = Header(my="N0CALL", my2="TEST")
    assert Header.from_radio(h.to_radio()) == Header(my="N0CALL  ", my2="TEST")

    config.put("radio/auto_connect", False)
    config.put("radio/username", "test")
    for mode in ("int", "ext"):
        config.put("dstar/mode", mode)
        config.put("ext/backend", "builtin")
        window = MainWindow()
        window.show()
        QTimer.singleShot(1500, window.close)
        QTimer.singleShot(2000, app.quit)
        app.exec()
        assert window.reflector_combo.count() > 0, "no reflectors loaded"
    print("smoke test OK")


if __name__ == "__main__":
    main()
