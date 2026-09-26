"""Icom Terminal Mode / Access Point link over USB (the IC-705's "External Gateway USB").

Port of G4KLX's CIcomController (with the local fixes: 0xFF idle bytes are
drained in bulk, and the port is reopened when the radio comes back).

Serial: 38400 baud, RTS/CTS. Frames are length-prefixed; byte 1 is the type:
  radio -> PC: 0x03 pong, 0x10 header, 0x12 data (0x40 in byte 3 = end),
               0x21 header ack, 0x23 data ack
  PC -> radio: 0x20 header, 0x22 data; one frame in flight, retried every 50 ms
"""

import collections
import re
import time

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtSerialPort import QSerialPort, QSerialPortInfo

from .protocol import DATA_SYNC_BYTES, END_PATTERN_BYTES, FRAMES_PER_SUPERFRAME, VOICE_FRAME_LENGTH, Header

ICOM_USB_VENDOR = 0x0C26
VALID_LENGTHS = (0x03, 0x04, 0x10, 0x2C)
VALID_TYPES = (0x03, 0x10, 0x12, 0x21, 0x23)

POLL = b"\xFF\xFF\xFF"
PING = b"\x02\x02\xFF"
POLL_FAST_MS = 100      # first 18 polls
PING_MS = 1000
RETRY_MS = 50
LOST_S = 5.0
REOPEN_MS = 2000


def find_icom_ports():
    """Serial ports of Icom radios. The IC-705 exposes two: CI-V first, then the D-STAR data port."""
    ports = [p for p in QSerialPortInfo.availablePorts() if p.vendorIdentifier() == ICOM_USB_VENDOR]
    # Natural order, so COM10 sorts after COM9 (ttyACM, COMn, cu.usbmodem...)
    return sorted(ports, key=lambda p: [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", p.systemLocation())])


def default_data_port():
    ports = find_icom_ports()
    if not ports:
        return ""
    # Linux by-id names end in -if00 (CI-V) / -if02 (data); on every OS the data port sorts last
    return ports[-1].systemLocation()


class IcomTerminal(QObject):
    log = Signal(str)
    connected = Signal(bool)
    header_received = Signal(object)          # Header
    data_received = Signal(bytes, bool)       # 12-byte DV frame, end of transmission

    def __init__(self, port_name=""):
        super().__init__()
        self.port_name = port_name
        self.serial = QSerialPort(self)
        self.serial.readyRead.connect(self._read)
        self.serial.errorOccurred.connect(self._serial_error)
        self.rx = bytearray()
        self.tx_queue = collections.deque()
        self.in_flight = None               # (frame bytes, kind, seq)
        self.tx_counter = 0
        self.pkt_counter = 0
        self.is_connected = False
        self.last_rx = 0.0
        self.poll_count = 0
        self.last_open_error = ""

        self.poll_timer = QTimer(self, singleShot=True)
        self.poll_timer.timeout.connect(self._poll)
        self.retry_timer = QTimer(self, interval=RETRY_MS)
        self.retry_timer.timeout.connect(self._retry)
        self.lost_timer = QTimer(self, interval=1000)
        self.lost_timer.timeout.connect(self._check_lost)
        self.reopen_timer = QTimer(self, singleShot=True, interval=REOPEN_MS)
        self.reopen_timer.timeout.connect(self.open)

    # --- public ---------------------------------------------------------------

    def open(self):
        name = self.port_name or default_data_port()
        if not name:
            if self.last_open_error != "missing":
                self.log.emit("USB: no se encuentra el puerto de datos de la radio")
                self.last_open_error = "missing"
            self.reopen_timer.start()
            return False
        self.serial.setPortName(name)
        self.serial.setBaudRate(38400)
        self.serial.setDataBits(QSerialPort.Data8)
        self.serial.setParity(QSerialPort.NoParity)
        self.serial.setStopBits(QSerialPort.OneStop)
        self.serial.setFlowControl(QSerialPort.HardwareControl)
        if not self.serial.open(QSerialPort.ReadWrite):
            message = f"USB: no se puede abrir {name}: {self.serial.errorString()}"
            if message != self.last_open_error:  # retried every 2 s: log each problem once
                self.log.emit(message)
                self.last_open_error = message
            self.reopen_timer.start()
            return False
        self.last_open_error = ""
        self.log.emit(f"USB: puerto {name} abierto")
        self._reset_link()
        self.lost_timer.start()
        return True

    def close(self):
        for t in (self.poll_timer, self.retry_timer, self.lost_timer, self.reopen_timer):
            t.stop()
        if self.serial.isOpen():
            self.serial.close()
        self._set_connected(False)

    def write_header(self, header):
        frame = bytes([0x29, 0x20]) + header.to_radio(with_crc=False)[:39] + b"\xFF"
        self.tx_counter = 0
        self.pkt_counter = 0
        self.tx_queue.append((frame, "header", 0))
        self._pump()

    def write_data(self, frame12, end=False):
        if end:
            data = bytes([0x10, 0x22, self.tx_counter, self.pkt_counter | 0x40]) + END_PATTERN_BYTES + b"\xFF"
            self.tx_queue.append((data, "data", self.tx_counter))
        else:
            seq = self.tx_counter
            data = bytes([0x10, 0x22, seq, self.pkt_counter]) + bytes(frame12) + b"\xFF"
            self.tx_counter = (self.tx_counter + 1) & 0xFF
            self.pkt_counter += 1
            if frame12[VOICE_FRAME_LENGTH:VOICE_FRAME_LENGTH + 3] == DATA_SYNC_BYTES or \
                    self.pkt_counter == FRAMES_PER_SUPERFRAME:
                self.pkt_counter = 0
            self.tx_queue.append((data, "data", seq))
        self._pump()

    # --- link management --------------------------------------------------------

    def _reset_link(self):
        self.rx.clear()
        self.tx_queue.clear()
        self.in_flight = None
        self.retry_timer.stop()
        self.poll_count = 0
        self.last_rx = time.monotonic()
        self.poll_timer.start(POLL_FAST_MS)

    def _set_connected(self, ok):
        if ok != self.is_connected:
            self.is_connected = ok
            self.log.emit("USB: radio conectada (Terminal Mode)" if ok else "USB: sin respuesta de la radio")
            self.connected.emit(ok)

    def _poll(self):
        if not self.serial.isOpen():
            return
        self.serial.write(PING if self.poll_count >= 18 else POLL)
        self.poll_count += 1
        self.poll_timer.start(PING_MS if self.poll_count >= 18 else POLL_FAST_MS)

    def _check_lost(self):
        if time.monotonic() - self.last_rx > LOST_S:
            self._set_connected(False)
            self._reset_link()

    def _serial_error(self, error):
        if error == QSerialPort.NoError or not self.serial.isOpen():
            return  # failures to open are handled in open()
        if error in (QSerialPort.ResourceError, QSerialPort.DeviceNotFoundError, QSerialPort.PermissionError):
            self.log.emit(f"USB: error del puerto ({self.serial.errorString()}), reintentando")
            self.close()
            self.reopen_timer.start()

    # --- transmit ---------------------------------------------------------------

    def _pump(self):
        if self.in_flight is None and self.tx_queue and self.serial.isOpen():
            self.in_flight = self.tx_queue.popleft()
            self.serial.write(self.in_flight[0])
            self.retry_timer.start()

    def _retry(self):
        if self.in_flight and self.serial.isOpen():
            self.serial.write(self.in_flight[0])

    def _acked(self):
        self.in_flight = None
        self.retry_timer.stop()
        self._pump()

    # --- receive ----------------------------------------------------------------

    def _read(self):
        self.rx.extend(bytes(self.serial.readAll().data()))
        while self.rx:
            # The radio fills the line with 0xFF idle bytes
            i = 0
            while i < len(self.rx) and self.rx[i] == 0xFF:
                i += 1
            if i:
                del self.rx[:i]
                continue
            length = self.rx[0]
            if length not in VALID_LENGTHS:
                del self.rx[0]
                continue
            if len(self.rx) < 2:
                return
            if self.rx[1] not in VALID_TYPES:
                del self.rx[0]
                continue
            if len(self.rx) < length:
                return
            frame = bytes(self.rx[:length])
            del self.rx[:length]
            self._handle(frame)

    def _handle(self, frame):
        kind = frame[1]
        self.last_rx = time.monotonic()
        if kind == 0x03:
            self._set_connected(True)
        elif kind == 0x10 and len(frame) >= 2 + 41:
            self._set_connected(True)
            self.header_received.emit(Header.from_radio(frame[2:43]))
        elif kind == 0x12 and len(frame) >= 16:
            end = bool(frame[3] & 0x40)
            self.data_received.emit(frame[4:16], end)
        elif kind == 0x21:
            if frame[2] == 0x00 and self.in_flight and self.in_flight[1] == "header":
                self._acked()
        elif kind == 0x23 and len(frame) >= 4:
            if frame[3] == 0x00 and self.in_flight and self.in_flight[1] == "data" and self.in_flight[2] == frame[2]:
                self._acked()
