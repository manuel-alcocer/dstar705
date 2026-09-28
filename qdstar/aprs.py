"""Forwarding of D-PRS positions to the APRS-IS network (aprs.fi and friends)."""

import time

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QAbstractSocket, QTcpSocket

from . import __version__
from .i18n import tr

DEFAULT_SERVER = "rotate.aprs2.net:14580"
TOCALL = "API705"              # what the IC-705 itself puts in its D-PRS packets
LOGIN_SSID = "10"              # conventional SSID of internet gateways
LOGIN_TIMEOUT = 15_000         # ms to get the server's logresp
IDLE_CLOSE = 15 * 60_000       # ms without packets before closing the connection
MIN_INTERVAL = 30              # s between two beacons of our own station
REPEAT_INTERVAL = 5 * 60       # s before an unchanged beacon of our own station is sent again


def passcode(callsign):
    """APRS-IS passcode of a call sign (the public algorithm every igate uses)."""
    call = callsign.upper().split("-")[0].strip()
    value = 0x73E2
    for i in range(0, len(call), 2):
        value ^= ord(call[i]) << 8
        if i + 1 < len(call):
            value ^= ord(call[i + 1])
    return value & 0x7FFF


def _latitude(lat):
    deg = int(abs(lat))
    minutes = round((abs(lat) - deg) * 60, 2)
    if minutes >= 60:
        deg, minutes = deg + 1, 0.0
    return f"{deg:02d}{minutes:05.2f}{'N' if lat >= 0 else 'S'}"


def _longitude(lon):
    deg = int(abs(lon))
    minutes = round((abs(lon) - deg) * 60, 2)
    if minutes >= 60:
        deg, minutes = deg + 1, 0.0
    return f"{deg:03d}{minutes:05.2f}{'E' if lon >= 0 else 'W'}"


def position_body(lat, lon, symbol="/[", altitude=None, comment=""):
    """Uncompressed position report without timestamp: '!DDMM.mmN/DDDMM.mmW[...'."""
    table, code = symbol[:2] if len(symbol) >= 2 else "/["
    body = f"!{_latitude(lat)}{table}{_longitude(lon)}{code}"
    if altitude is not None:
        feet = max(-99999, min(999999, round(altitude / 0.3048)))
        body += f"/A={feet:06d}" if feet >= 0 else f"/A=-{-feet:05d}"
    comment = "".join(c for c in comment if 32 <= ord(c) < 127).strip()
    return body + comment


def packet(source, body, path):
    return f"{source.upper()}>{TOCALL},{path}:{body}"


class AprsIs(QObject):
    """Send-only APRS-IS client: connects when there is something to send, closes when idle."""

    log = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.callsign = ""
        self.server = DEFAULT_SERVER
        self.queue = []
        self.verified = False
        self.buffer = b""
        self.last_own = ("", 0.0)
        self.socket = QTcpSocket(self)
        self.socket.connected.connect(self._on_connected)
        self.socket.readyRead.connect(self._on_ready_read)
        self.socket.errorOccurred.connect(self._on_error)
        self.socket.disconnected.connect(self._on_disconnected)
        self.login_timer = QTimer(self, singleShot=True, interval=LOGIN_TIMEOUT)
        self.login_timer.timeout.connect(self._login_timeout)
        self.idle_timer = QTimer(self, singleShot=True, interval=IDLE_CLOSE)
        self.idle_timer.timeout.connect(self.close)

    @property
    def login(self):
        return f"{self.callsign}-{LOGIN_SSID}"

    def configure(self, callsign, server):
        callsign = callsign.upper().split("-")[0].strip()
        server = server.strip() or DEFAULT_SERVER
        if (callsign, server) != (self.callsign, self.server):
            self.close()
        self.callsign, self.server = callsign, server

    def send_own(self, source, body):
        """Beacon of our own station: skipped when an identical one went out recently."""
        last_body, last_time = self.last_own
        age = time.monotonic() - last_time
        if age < MIN_INTERVAL or (body == last_body and age < REPEAT_INTERVAL):
            return False
        self.last_own = (body, time.monotonic())
        self.send(packet(source, body, "TCPIP*"))
        return True

    def send_heard(self, source, body):
        """Position of another station heard over D-STAR, gated with our login as the igate."""
        self.send(packet(source, body, f"DSTAR*,qAR,{self.login}"))

    def send(self, line):
        if not self.callsign:
            return
        self.queue.append(line)
        if self.verified:
            self._flush()
        elif self.socket.state() == QAbstractSocket.UnconnectedState:
            host, _, port = self.server.rpartition(":")
            if not host or not port.isdigit():
                host, port = self.server, "14580"
            self.log.emit(tr("APRS-IS: connecting to {server}", server=f"{host}:{port}"))
            self.socket.connectToHost(host, int(port))
            self.login_timer.start()

    def close(self):
        self.login_timer.stop()
        self.idle_timer.stop()
        self.verified = False
        if self.socket.state() != QAbstractSocket.UnconnectedState:
            self.socket.abort()

    # --- internals -----------------------------------------------------------

    def _write(self, line):
        self.socket.write((line + "\r\n").encode("ascii", "replace"))

    def _flush(self):
        while self.queue:
            line = self.queue.pop(0)
            self._write(line)
            self.log.emit(tr("APRS-IS ← {packet}", packet=line))
        self.idle_timer.start()

    def _on_connected(self):
        self._write(f"user {self.login} pass {passcode(self.callsign)} vers QDStar {__version__}")

    def _on_ready_read(self):
        self.buffer += bytes(self.socket.readAll())
        *lines, self.buffer = self.buffer.split(b"\n")
        for raw in lines:
            line = raw.decode("ascii", "replace").strip()
            if not line.startswith("# logresp"):
                continue      # server banner and keepalives
            self.login_timer.stop()
            if " verified" in line:
                self.verified = True
                self._flush()
            else:
                self.log.emit(tr("APRS-IS: the server did not verify {login}: {reply}", login=self.login, reply=line))
                self.queue.clear()
                self.close()

    def _login_timeout(self):
        self.log.emit(tr("APRS-IS: no answer from {server}", server=self.server))
        self.queue.clear()
        self.close()

    def _on_error(self, _error):
        if self.queue:
            self.log.emit(tr("APRS-IS: {error}", error=self.socket.errorString()))
        self.queue.clear()
        self.close()

    def _on_disconnected(self):
        self.verified = False
        self.login_timer.stop()
        self.idle_timer.stop()
