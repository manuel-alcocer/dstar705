"""Icom network (UDP) remote protocol client: control stream + CI-V stream.

Reimplemented from wfview (icomudpbase/icomudphandler/icomudpcivdata),
which is itself based on kappanhang. Audio is not used.
"""

import random
import socket
import struct
import time

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QHostAddress, QUdpSocket

PING_PERIOD = 500
IDLE_PERIOD = 100
AREYOUTHERE_PERIOD = 500
TOKEN_RENEWAL = 60000
STALE_TIMEOUT = 5.0  # seconds without any packet from the radio
TX_BUFFER = 300

CONTROL_SIZE = 0x10
PING_SIZE = 0x15
TOKEN_SIZE = 0x40
STATUS_SIZE = 0x50
LOGIN_RESPONSE_SIZE = 0x60
LOGIN_SIZE = 0x80
CONNINFO_SIZE = 0x90
CAPABILITIES_SIZE = 0x42
RADIO_CAP_SIZE = 0x66
CIV_HEADER_SIZE = 0x15

_PASSCODE = bytes(32) + bytes([
    0x47, 0x5d, 0x4c, 0x42, 0x66, 0x20, 0x23, 0x46, 0x4e, 0x57, 0x45, 0x3d, 0x67, 0x76, 0x60, 0x41, 0x62, 0x39, 0x59,
    0x2d, 0x68, 0x7e, 0x7c, 0x65, 0x7d, 0x49, 0x29, 0x72, 0x73, 0x78, 0x21, 0x6e, 0x5a, 0x5e, 0x4a, 0x3e, 0x71, 0x2c,
    0x2a, 0x54, 0x3c, 0x3a, 0x63, 0x4f, 0x43, 0x75, 0x27, 0x79, 0x5b, 0x35, 0x70, 0x48, 0x6b, 0x56, 0x6f, 0x34, 0x32,
    0x6c, 0x30, 0x61, 0x6d, 0x7b, 0x2f, 0x4b, 0x64, 0x38, 0x2b, 0x2e, 0x50, 0x40, 0x3f, 0x55, 0x33, 0x37, 0x25, 0x77,
    0x24, 0x26, 0x74, 0x6a, 0x28, 0x53, 0x4d, 0x69, 0x22, 0x5c, 0x44, 0x31, 0x36, 0x58, 0x3b, 0x7a, 0x51, 0x5f, 0x52,
]) + bytes(32)


def passcode(text):
    """Icom's obfuscation of username/password (max 16 chars)."""
    out = bytearray()
    for i, ch in enumerate(text.encode("latin-1")[:16]):
        p = ch + i
        if p > 126:
            p = 32 + p % 127
        out.append(_PASSCODE[p])
    return bytes(out)


def local_ip_towards(host):
    """IPv4 address of the local interface used to reach host."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect((host, 9))
        return s.getsockname()[0]


class _Stream(QObject):
    """Common transport: handshake, pings, idles, tracked packets and retransmits."""

    log = Signal(str)

    def __init__(self, host, port, local_ip, local_port=0, parent=None):
        super().__init__(parent)
        self.host = QHostAddress(host)
        self.port = port
        self.sock = QUdpSocket(self)
        if not self.sock.bind(QHostAddress.AnyIPv4, local_port):
            raise OSError(f"Cannot bind UDP port {local_port}: {self.sock.errorString()}")
        self.local_port = self.sock.localPort()
        a = [int(x) for x in local_ip.split(".")]
        self.my_id = (a[2] << 24) | (a[3] << 16) | self.local_port
        self.remote_id = 0
        self.send_seq = 1
        self.ping_seq = 0
        self.tx_buffer = {}
        self.last_rx = time.monotonic()
        self.sock.readyRead.connect(self._read)

        self.ayt_timer = QTimer(self, interval=AREYOUTHERE_PERIOD)
        self.ayt_timer.timeout.connect(lambda: self.send_control(0x03, tracked=False))
        self.ping_timer = QTimer(self, interval=PING_PERIOD)
        self.ping_timer.timeout.connect(self._send_ping)
        self.idle_timer = QTimer(self, interval=IDLE_PERIOD)
        self.idle_timer.timeout.connect(lambda: self.send_control(0x00))

    # --- sending -------------------------------------------------------

    def _write(self, data):
        self.sock.writeDatagram(data, self.host, self.port)

    def _header(self, size, ptype=0, seq=0):
        return bytearray(struct.pack("<IHHII", size, ptype, seq, self.my_id, self.remote_id)) + bytes(size - 0x10)

    def send_control(self, ptype, tracked=True, seq=0):
        pkt = self._header(CONTROL_SIZE, ptype, seq)
        if tracked:
            self.send_tracked(pkt)
        else:
            self._write(bytes(pkt))

    def send_tracked(self, pkt):
        pkt = bytearray(pkt)
        struct.pack_into("<H", pkt, 6, self.send_seq)
        self.tx_buffer[self.send_seq] = bytes(pkt)
        if len(self.tx_buffer) > TX_BUFFER:
            self.tx_buffer.pop(next(iter(self.tx_buffer)))
        self.send_seq = (self.send_seq + 1) & 0xFFFF
        self._write(bytes(pkt))
        if self.idle_timer.isActive():
            self.idle_timer.start()

    def _send_ping(self):
        pkt = self._header(PING_SIZE, 0x07, self.ping_seq)
        struct.pack_into("<BI", pkt, 0x10, 0, int(time.time() * 1000) % 86_400_000)
        self._write(bytes(pkt))

    def start(self):
        self.send_control(0x03, tracked=False)
        self.ayt_timer.start()

    def stop(self):
        for t in (self.ayt_timer, self.ping_timer, self.idle_timer):
            t.stop()

    def close(self):
        self.stop()
        self.sock.close()

    # --- receiving -----------------------------------------------------

    def _read(self):
        while self.sock.state() == QUdpSocket.BoundState and self.sock.hasPendingDatagrams():
            dg = self.sock.receiveDatagram()
            data = bytes(dg.data())
            if len(data) < 0x10:
                continue
            self.last_rx = time.monotonic()
            length, ptype, seq, sent_id = struct.unpack_from("<IHHI", data)
            if ptype == 0x01:
                self._retransmit(data, seq)
                continue
            if len(data) == PING_SIZE and ptype == 0x07:
                if data[0x10] == 0x00:  # radio pings us: echo it back (its length field is not reliable)
                    pkt = self._header(PING_SIZE, 0x07, seq)
                    pkt[0x10] = 0x01
                    pkt[0x11:0x15] = data[0x11:0x15]
                    self._write(bytes(pkt))
                elif seq == self.ping_seq:
                    self.ping_seq = (self.ping_seq + 1) & 0xFFFF
                continue
            if len(data) == CONTROL_SIZE:
                if ptype == 0x04:  # I am here
                    self.remote_id = sent_id
                    self.ayt_timer.stop()
                    self.send_control(0x06, tracked=False, seq=1)  # are you ready
                    self.ping_timer.start()
                    self.idle_timer.start()
                    self.on_here()
                    continue
                if ptype == 0x06:  # I am ready
                    self.remote_id = sent_id
                    self.on_ready()
                    continue
                if ptype == 0x05:
                    self.on_disconnect()
                    continue
            self.on_packet(data)

    def _retransmit(self, data, seq):
        if len(data) == CONTROL_SIZE:
            seqs = [seq]
        else:
            seqs = [struct.unpack_from("<H", data, i)[0] for i in range(0x10, len(data) - 1, 2)]
        for s in seqs:
            pkt = self.tx_buffer.get(s)
            if pkt:
                self._write(pkt)
            else:
                self.send_control(0x00, tracked=False, seq=s)

    # hooks
    def on_here(self):
        pass

    def on_ready(self):
        pass

    def on_disconnect(self):
        pass

    def on_packet(self, data):
        pass


class CivStream(_Stream):
    """CI-V data stream (port announced by the radio after login)."""

    civ = Signal(bytes)
    opened = Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.inner_seq = 0
        self.is_open = False
        self.last_civ = 0.0
        # Like wfview: keep asking the radio to start CI-V data until some arrives
        self.open_timer = QTimer(self, interval=100)
        self.open_timer.timeout.connect(self._retry_open)
        self.civ_watchdog = QTimer(self, interval=500)
        self.civ_watchdog.timeout.connect(self._check_civ)

    def on_ready(self):
        self._send_open()
        self.open_timer.start()
        self.civ_watchdog.start()

    def _retry_open(self):
        self._send_open()
        # A probe (read transceiver ID) makes the radio answer even when idle
        self.send_civ(b"\xFE\xFE\xA4\xE0\x19\x00\xFD")

    def _check_civ(self):
        if self.is_open and time.monotonic() - self.last_civ > 2.0 and not self.open_timer.isActive():
            self.open_timer.start(500)

    def stop(self):
        self.open_timer.stop()
        self.civ_watchdog.stop()
        super().stop()

    def _send_open(self, close=False):
        pkt = self._header(0x16)
        struct.pack_into("<H", pkt, 0x10, 0x01C0)
        struct.pack_into(">H", pkt, 0x13, self.inner_seq)
        pkt[0x15] = 0x00 if close else 0x04
        self.inner_seq = (self.inner_seq + 1) & 0xFFFF
        self.send_tracked(pkt)

    def send_civ(self, frame):
        pkt = self._header(CIV_HEADER_SIZE)
        pkt[0] = 0  # length fixed below
        struct.pack_into("<I", pkt, 0, CIV_HEADER_SIZE + len(frame))
        pkt[0x10] = 0xC1
        struct.pack_into("<H", pkt, 0x11, len(frame))
        struct.pack_into(">H", pkt, 0x13, self.inner_seq)
        self.inner_seq = (self.inner_seq + 1) & 0xFFFF
        self.send_tracked(bytes(pkt) + bytes(frame))

    def on_packet(self, data):
        if len(data) <= CIV_HEADER_SIZE:
            return
        datalen = struct.unpack_from("<H", data, 0x11)[0]
        if datalen + CIV_HEADER_SIZE != len(data):
            return
        self.last_civ = time.monotonic()
        self.open_timer.stop()
        if not self.is_open:
            self.is_open = True
            self.opened.emit()
        self.civ.emit(data[CIV_HEADER_SIZE:])

    def close(self):
        # Same goodbye as wfview: stop CI-V data, then disconnect this stream
        self._send_open(close=True)
        self.send_control(0x05, tracked=False)
        super().close()


class IcomConnection(QObject):
    """Logs into the radio and exposes a CI-V byte stream.

    Signals report the state machine so the UI can light its LEDs.
    """

    log = Signal(str)
    state_changed = Signal(str)  # disconnected, connecting, authenticated, connected
    civ_received = Signal(bytes)
    radio_info = Signal(dict)
    error = Signal(str)

    def __init__(self, host, username, password, control_port=50001, client_name="dstar705", parent=None):
        super().__init__(parent)
        self.host = host
        self.username = username
        self.password = password
        self.control_port = control_port
        self.client_name = client_name[:16]
        self.control = None
        self.civ_stream = None
        self.state = "disconnected"
        self.watchdog = QTimer(self, interval=1000)
        self.watchdog.timeout.connect(self._check_alive)
        self.token_timer = QTimer(self, interval=TOKEN_RENEWAL)
        self.token_timer.timeout.connect(lambda: self._send_token(0x05))
        self.reconnect_timer = QTimer(self, singleShot=True, interval=5000)
        self.reconnect_timer.timeout.connect(self.connect_radio)
        self.auto_reconnect = True

    # --- public --------------------------------------------------------

    def connect_radio(self):
        self._teardown(send_bye=False)
        try:
            self.local_ip = local_ip_towards(self.host)
            self.control = _Stream(self.host, self.control_port, self.local_ip, parent=self)
        except OSError as exc:
            self._fail(f"Sin red hacia {self.host}: {exc}")
            return
        self.control.on_ready = self._send_login
        self.control.on_packet = self._on_control_packet
        self.control.on_disconnect = lambda: self._fail("La radio cerró la sesión")
        self.auth_seq = 0x30
        self.tok_request = random.getrandbits(16)
        self.token = 0
        self.radio = None
        self.stream_requested = False
        self._set_state("connecting")
        self.log.emit(f"Conectando con {self.host}:{self.control_port}")
        self.control.start()
        self.watchdog.start()

    def disconnect_radio(self):
        self.auto_reconnect = False
        self.reconnect_timer.stop()
        self._teardown(send_bye=True)
        self._set_state("disconnected")

    def send_civ(self, frame):
        if self.civ_stream and self.civ_stream.is_open:
            self.civ_stream.send_civ(frame)
            return True
        return False

    # --- internals -----------------------------------------------------

    def _set_state(self, state):
        if state != self.state:
            self.state = state
            self.state_changed.emit(state)

    def _fail(self, message):
        self.error.emit(message)
        self.log.emit(message)
        self._teardown(send_bye=False)
        self._set_state("disconnected")
        if self.auto_reconnect:
            self.reconnect_timer.start()

    def _teardown(self, send_bye):
        self.watchdog.stop()
        self.token_timer.stop()
        if self.civ_stream:
            self.civ_stream.close()
            self.civ_stream.deleteLater()
            self.civ_stream = None
        if self.control:
            if send_bye and self.token:
                self._send_token(0x01)  # token removal
                self.control.send_control(0x05, tracked=False)
            self.control.close()
            self.control.deleteLater()
            self.control = None

    def _check_alive(self):
        streams = [s for s in (self.control, self.civ_stream) if s]
        if self.state == "connected" and any(time.monotonic() - s.last_rx > STALE_TIMEOUT for s in streams):
            self._fail("Sin respuesta de la radio (timeout)")
        elif self.state == "authenticated" and time.monotonic() - self.auth_time > 12:
            self._fail("La radio no abre el stream: seguramente conserva una sesión anterior colgada. "
                       "Si persiste, apaga y enciende la radio.")
        elif self.state == "connecting" and time.monotonic() - self.control.last_rx > 15:
            self.control.last_rx = time.monotonic()
            self.log.emit("La radio no responde, sigo intentándolo…")

    def _inner_header(self, size, request_type):
        pkt = self.control._header(size)
        struct.pack_into(">I", pkt, 0x10, size - 0x10)
        pkt[0x14] = 0x01
        pkt[0x15] = request_type
        struct.pack_into(">H", pkt, 0x16, self.auth_seq)
        self.auth_seq = (self.auth_seq + 1) & 0xFFFF
        struct.pack_into("<H", pkt, 0x1A, self.tok_request)
        struct.pack_into("<I", pkt, 0x1C, self.token)
        return pkt

    def _send_login(self):
        self.log.emit("Radio lista, enviando login")
        pkt = self._inner_header(LOGIN_SIZE, 0x00)
        user, pw = passcode(self.username), passcode(self.password)
        pkt[0x40:0x40 + len(user)] = user
        pkt[0x50:0x50 + len(pw)] = pw
        name = self.client_name.encode()
        pkt[0x60:0x60 + len(name)] = name
        self.control.send_tracked(pkt)

    def _send_token(self, magic):
        if not self.control:
            return
        pkt = self._inner_header(TOKEN_SIZE, magic)
        struct.pack_into(">H", pkt, 0x24, 0x0798)
        self.control.send_tracked(pkt)

    def _request_stream(self):
        r = self.radio
        pkt = self._inner_header(CONNINFO_SIZE, 0x03)
        if r["commoncap"] == 0x8010:
            struct.pack_into("<H", pkt, 0x27, 0x8010)
            pkt[0x2A:0x30] = r["mac"]
        else:
            pkt[0x20:0x30] = r["guid"]
        name = r["name"].encode()[:32]
        pkt[0x40:0x40 + len(name)] = name
        user = passcode(self.username)
        pkt[0x60:0x60 + len(user)] = user
        pkt[0x70] = 0x01  # rx enable (the radio expects it; we just ignore audio)
        pkt[0x71] = 0x00  # tx disable
        pkt[0x72] = 0x01  # rx codec: uLaw 1ch, smallest stream
        pkt[0x73] = 0x00
        struct.pack_into(">III", pkt, 0x74, 8000, 0, self.civ_local_port)
        struct.pack_into(">II", pkt, 0x80, self.audio_local_port, 0)
        pkt[0x88] = 0x01
        self.stream_requested = True
        self.control.send_tracked(pkt)

    @staticmethod
    def _free_port():
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.bind(("", 0))
            return s.getsockname()[1]

    def _on_control_packet(self, data):
        size = len(data)
        ptype = struct.unpack_from("<H", data, 4)[0]
        if ptype == 0x01:
            return
        if size == LOGIN_RESPONSE_SIZE:
            error = struct.unpack_from("<I", data, 0x30)[0]
            if error == 0xFEFFFFFF:
                self.auto_reconnect = False
                self._fail("Usuario o contraseña incorrectos")
                return
            tok_request = struct.unpack_from("<H", data, 0x1A)[0]
            if tok_request == self.tok_request and not self.token:
                self.token = struct.unpack_from("<I", data, 0x1C)[0]
                conn = data[0x40:0x50].split(b"\0")[0].decode(errors="replace")
                self.log.emit(f"Login OK (conexión {conn})")
                self._send_token(0x02)
                self.token_timer.start()
                self.auth_time = time.monotonic()
                self._set_state("authenticated")
        elif size == TOKEN_SIZE:
            if data[0x15] == 0x05 and data[0x14] == 0x02:
                response = struct.unpack_from("<I", data, 0x30)[0]
                if response == 0xFFFFFFFF:
                    self.log.emit("La radio rechazó la renovación del token")
                    self.token = struct.unpack_from("<I", data, 0x1C)[0]
                    if self.radio:
                        self._request_stream()
        elif size == STATUS_SIZE:
            error = struct.unpack_from("<I", data, 0x30)[0]
            if error == 0xFFFFFFFF:
                self._fail("Conexión rechazada por la radio (prueba a reiniciarla)")
            elif error == 0 and data[0x40] == 0x01:
                self._fail("La radio desconectó el stream")
            else:
                civ_port = struct.unpack_from(">H", data, 0x42)[0]
                if civ_port and not self.civ_stream:
                    self._open_civ(civ_port)
        elif size == CONNINFO_SIZE:
            busy = struct.unpack_from("<I", data, 0x60)[0]
            computer = data[0x64:0x74].split(b"\0")[0].decode(errors="replace")
            if self.radio and not self.stream_requested:
                if busy and computer and computer != self.client_name:
                    ip = socket.inet_ntoa(data[0x84:0x88])
                    self._fail(f"Radio ocupada por {computer} ({ip}); cierra wfview u otro cliente")
                else:
                    self.civ_local_port = self._free_port()
                    self.audio_local_port = self._free_port()
                    self._request_stream()
        elif size > CAPABILITIES_SIZE and (size - CAPABILITIES_SIZE) % RADIO_CAP_SIZE == 0:
            cap = data[CAPABILITIES_SIZE:CAPABILITIES_SIZE + RADIO_CAP_SIZE]
            self.radio = {
                "guid": cap[0:16],
                "commoncap": struct.unpack_from("<H", cap, 0x07)[0],
                "mac": cap[0x0A:0x10],
                "name": cap[0x10:0x30].split(b"\0")[0].decode(errors="replace"),
                "audio": cap[0x30:0x50].split(b"\0")[0].decode(errors="replace"),
                "civ": cap[0x52],
            }
            self.log.emit(f"Radio: {self.radio['name']} (CI-V 0x{self.radio['civ']:02X})")
            self.radio_info.emit(dict(self.radio))

    def _open_civ(self, civ_port):
        self.log.emit(f"Abriendo stream CI-V (puerto remoto {civ_port})")
        self.civ_stream = CivStream(self.host, civ_port, self.local_ip, self.civ_local_port, parent=self)
        self.civ_stream.civ.connect(self.civ_received)
        self.civ_stream.opened.connect(self._civ_opened)
        self.civ_stream.start()

    def _civ_opened(self):
        self.log.emit("Stream CI-V abierto")
        self._set_state("connected")
