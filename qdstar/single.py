"""Single instance: a second launch brings the running window to the front and exits.

Two instances would fight over the radio's single network session and the USB
serial port. The first instance listens on a per-user local socket (a named pipe
on Windows); later ones connect to it, ask it to show itself and quit.
"""

import getpass
import re

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def _server_name():
    user = re.sub(r"[^A-Za-z0-9_.-]", "_", getpass.getuser() or "user")
    return f"qdstar-{user}"


def ask_running_instance():
    """True if another instance is running (it has been asked to come to the front)."""
    socket = QLocalSocket()
    socket.connectToServer(_server_name())
    if not socket.waitForConnected(500):
        return False
    socket.write(b"show\n")
    socket.flush()
    socket.waitForBytesWritten(500)
    socket.disconnectFromServer()
    return True


class InstanceServer(QObject):
    show_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.server = QLocalServer(self)
        name = _server_name()
        if not self.server.listen(name):
            # A crashed instance can leave the socket behind: clear it and retry
            QLocalServer.removeServer(name)
            self.server.listen(name)
        self.server.newConnection.connect(self._accept)

    def _accept(self):
        while self.server.hasPendingConnections():
            connection = self.server.nextPendingConnection()
            connection.readyRead.connect(lambda c=connection: self._read(c))
            connection.disconnected.connect(connection.deleteLater)

    def _read(self, connection):
        if b"show" in bytes(connection.readAll().data()):
            self.show_requested.emit()
