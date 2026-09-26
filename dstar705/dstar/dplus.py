"""DPlus (REF reflectors): authentication and an outgoing "dongle" link.

Port of ircDDBGateway's CDPlusAuthenticator / CDPlusHandler / CDPlusProtocolHandler.
"""

import socket
import struct
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QHostAddress, QUdpSocket

from ..qtutil import safe_emit

from .protocol import DPLUS_PORT, END_PATTERN_BYTES, NULL_AMBE_DATA_BYTES, Header, ccitt_crc, pad

AUTH_HOST = "auth.dstargateway.org"
AUTH_PORT = 20001
AUTH_REFRESH = 6 * 3600

POLL_MS = 1000
POLL_TIMEOUT_S = 30
HEADER_REPEATS = 5


def _recv_exact(sock, n):
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise OSError("connection closed")
        data += chunk
    return data


def authenticate(login):
    """Register the call sign with the DPlus trust server; returns {'REF001': 'ip', ...}.

    REF reflectors only accept links from call signs that authenticated recently.
    """
    packet = bytearray(b" " * 56)
    packet[0:4] = b"\x38\xC0\x01\x00"
    packet[4:4 + len(login)] = login.upper().encode()[:8]
    packet[12:20] = b"DV019999"
    packet[28:32] = b"W7IB"
    packet[32] = ord("2")
    packet[40:47] = b"DHS0257"
    hosts = {}
    with socket.create_connection((AUTH_HOST, AUTH_PORT), timeout=15) as sock:
        sock.sendall(bytes(packet))
        while True:
            try:
                head = _recv_exact(sock, 2)
            except OSError:
                break
            length = (head[1] & 0x0F) * 256 + head[0]
            body = head + _recv_exact(sock, length - 2)
            if (body[1] & 0xC0) != 0xC0 or body[2] != 0x01:
                break
            for i in range(8, length - 25, 26):
                address = body[i:i + 16].split(b"\0")[0].decode(errors="replace").strip()
                name = body[i + 16:i + 24].decode(errors="replace").strip()
                active = bool(body[i + 25] & 0x80)
                if address and name and active and name.startswith("REF"):
                    hosts[name[:6]] = address
    return hosts


class DPlusAuthenticator(QObject):
    """Authenticates in a worker thread at start-up and every 6 hours."""

    done = Signal(bool, dict)
    log = Signal(str)

    def __init__(self, login):
        super().__init__()
        self.login = login
        self.hosts = {}
        self.authenticated_at = 0.0
        self.timer = QTimer(self, interval=AUTH_REFRESH * 1000)
        self.timer.timeout.connect(self.start)

    def start(self):
        self.timer.start()
        threading.Thread(target=self._run, daemon=True, name="dplus-auth").start()

    def _run(self):
        try:
            hosts = authenticate(self.login)
            self.hosts = hosts
            self.authenticated_at = time.time()
            safe_emit(self.log, f"DPlus: autenticado como {self.login} ({len(hosts)} reflectores REF)")
            safe_emit(self.done, True, hosts)
        except OSError as exc:
            safe_emit(self.log, f"DPlus: fallo de autenticación en {AUTH_HOST}: {exc}")
            safe_emit(self.done, False, {})


class DPlusLink(QObject):
    """Outgoing DPlus link to one REF module, as a dongle."""

    log = Signal(str)
    state_changed = Signal(str)                 # linking, linked, refused, failed, unlinked
    header_received = Signal(int, object)       # stream id, Header
    data_received = Signal(int, int, bytes, bool)  # stream id, seq, 12-byte frame, end

    def __init__(self, reflector, address, login, terminal_call):
        super().__init__()
        self.reflector = pad(reflector)            # 'REF001 C'
        self.address = QHostAddress(address)
        self.login = login.upper().strip()
        # RPT1 on outgoing headers: login call sign with the terminal's module letter
        self.rpt1 = pad(self.login)[:7] + pad(terminal_call)[7]
        self.state = "idle"
        self.last_rx = 0.0
        self.try_count = 0
        self.sock = QUdpSocket(self)
        self.sock.bind(QHostAddress.AnyIPv4, 0)
        self.sock.readyRead.connect(self._read)
        self.poll_timer = QTimer(self, interval=POLL_MS)
        self.poll_timer.timeout.connect(self._poll)
        self.try_timer = QTimer(self, singleShot=True)
        self.try_timer.timeout.connect(self._retry)

    # --- control ------------------------------------------------------------------

    def link(self):
        self.try_count = 0
        self._set_state("linking")
        self.last_rx = time.monotonic()
        self._send(b"\x05\x00\x18\x00\x01")
        self.try_timer.start(1000)
        self.poll_timer.start()

    def unlink(self):
        self.try_timer.stop()
        self.poll_timer.stop()
        if self.state in ("linking", "linked"):
            for _ in range(2):
                self._send(b"\x05\x00\x18\x00\x00")
        self._set_state("unlinked")

    def close(self):
        self.unlink()
        self.sock.close()

    # --- voice ------------------------------------------------------------------------

    def send_header(self, stream_id, header):
        if self.state != "linked":
            return
        h = header.with_(flag1=0, flag2=0, flag3=0, rpt1=self.rpt1, rpt2=self.reflector)
        body = bytes([0, 0, 0]) + h.callsigns()
        pkt = (b"\x3A\x80DSVT\x10\x00\x00\x00\x20\x00\x00\x00"
               + struct.pack("<H", stream_id) + b"\x80" + body + ccitt_crc(body))
        for _ in range(HEADER_REPEATS):
            self._send(pkt)

    def send_data(self, stream_id, seq, frame, end=False):
        if self.state != "linked":
            return
        head = b"DSVT\x20\x00\x00\x00\x20\x00\x00\x00" + struct.pack("<H", stream_id)
        if end:
            self._send(b"\x20\x80" + head + bytes([seq | 0x40]) + NULL_AMBE_DATA_BYTES + END_PATTERN_BYTES[:6])
        else:
            self._send(b"\x1D\x80" + head + bytes([seq]) + bytes(frame))

    # --- internals ------------------------------------------------------------------

    def _set_state(self, state):
        if state != self.state:
            self.state = state
            self.state_changed.emit(state)

    def _send(self, data):
        self.sock.writeDatagram(data, self.address, DPLUS_PORT)

    def _poll(self):
        if self.state == "linked":
            self._send(b"\x03\x60\x00")
        if self.state in ("linking", "linked") and time.monotonic() - self.last_rx > POLL_TIMEOUT_S:
            self.log.emit(f"DPlus: {self.reflector.strip()} no responde, reenlazando")
            self.link()

    def _retry(self):
        if self.state != "linking":
            return
        self._send(b"\x05\x00\x18\x00\x01")
        self.try_count += 1
        self.try_timer.start(min(60, 2 ** min(self.try_count, 6)) * 1000)

    def _read(self):
        while self.sock.state() == QUdpSocket.BoundState and self.sock.hasPendingDatagrams():
            data = bytes(self.sock.receiveDatagram().data())
            self.last_rx = time.monotonic()
            self._handle(data)

    def _handle(self, data):
        if len(data) >= 6 and data[2:6] == b"DSVT":
            if data[0] == 0x3A and data[1] == 0x80 and len(data) >= 58:
                stream_id = struct.unpack_from("<H", data, 14)[0]
                self.header_received.emit(stream_id, Header.from_radio(data[17:58]))
            elif data[0] in (0x1D, 0x20) and data[1] == 0x80 and len(data) >= 29:
                stream_id = struct.unpack_from("<H", data, 14)[0]
                seq = data[16]
                end = bool(seq & 0x40)
                self.data_received.emit(stream_id, seq & 0x1F, data[17:29], end)
            return
        if len(data) == 3:
            return  # poll from the reflector
        if len(data) == 5 and self.state == "linking" and data[4] == 0x01:
            # LINK1 echoed: identify ourselves (LINK2)
            pkt = bytearray(28)
            pkt[0:4] = b"\x1C\xC0\x04\x00"
            login = self.login.encode()[:16]
            pkt[4:4 + len(login)] = login
            pkt[20:28] = b"DV019999"
            self._send(bytes(pkt))
        elif len(data) == 5 and data[4] == 0x00:
            self.log.emit(f"DPlus: {self.reflector.strip()} ha cerrado el enlace")
            self.poll_timer.stop()
            self._set_state("unlinked")
        elif len(data) == 8:
            reply = data[4:8].decode(errors="replace")
            self.try_timer.stop()
            if reply == "OKRW":
                self.log.emit(f"DPlus: enlazado a {self.reflector.strip()} (OKRW)")
                self._set_state("linked")
            else:
                self.log.emit(f"DPlus: {self.reflector.strip()} rechaza el enlace ({reply})")
                self._send(b"\x05\x00\x18\x00\x00")
                self.poll_timer.stop()
                self._set_state("refused")
