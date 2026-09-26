"""DCS (DCS and XLX reflectors) and DExtra (XRF and XLX) outgoing links.

Port of ircDDBGateway's CDCSHandler / CDExtraHandler and the matching packet codecs.
"""

import struct
import time

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QHostAddress, QUdpSocket

from .protocol import DCS_PORT, DEXTRA_PORT, END_PATTERN_BYTES, NULL_AMBE_DATA_BYTES, Header, ccitt_crc, pad
from ..i18n import tr

LINK_RETRY_MS = 1000
POLL_TIMEOUT_S = 60
DCS_HTML = ("<table border=\"0\" width=\"95%\"><tr><td width=\"4%\"><img border=\"0\" src=dongle.jpg></td>"
            "<td width=\"96%\"><font size=\"2\"><b>DONGLE</b> QDStar</font></td></tr></table>")


class _Link(QObject):
    """Common state machine: link request with retries, keepalives, inactivity timeout."""

    log = Signal(str)
    state_changed = Signal(str)                    # linking, linked, refused, failed, unlinked
    header_received = Signal(int, object)          # stream id, Header
    data_received = Signal(int, int, bytes, bool)  # stream id, seq, 12-byte frame, end

    NAME = "?"
    PORT = 0
    POLL_MS = 5000

    def __init__(self, reflector, address, login, terminal_call):
        super().__init__()
        self.reflector = pad(reflector)            # 'DCS214 D'
        self.address = QHostAddress(address)
        self.repeater = pad(pad(login)[:7] + pad(terminal_call)[7])   # 'N0CALL B'
        self.state = "idle"
        self.last_rx = 0.0
        self.try_count = 0
        self.sock = QUdpSocket(self)
        self.sock.bind(QHostAddress.AnyIPv4, 0)
        self.sock.readyRead.connect(self._read)
        self.poll_timer = QTimer(self, interval=self.POLL_MS)
        self.poll_timer.timeout.connect(self._poll)
        self.try_timer = QTimer(self, singleShot=True)
        self.try_timer.timeout.connect(self._retry)

    def link(self):
        self.try_count = 0
        self.last_rx = time.monotonic()
        self._set_state("linking")
        self._send(self._link_packet())
        self.try_timer.start(LINK_RETRY_MS)
        self.poll_timer.start()

    def unlink(self):
        self.try_timer.stop()
        self.poll_timer.stop()
        if self.state in ("linking", "linked"):
            for _ in range(2):
                self._send(self._unlink_packet())
        self._set_state("unlinked")

    def close(self):
        self.unlink()
        self.sock.close()

    def _set_state(self, state):
        if state != self.state:
            self.state = state
            self.state_changed.emit(state)

    def _send(self, data):
        self.sock.writeDatagram(data, self.address, self.PORT)

    def _retry(self):
        if self.state != "linking":
            return
        self._send(self._link_packet())
        self.try_count += 1
        self.try_timer.start(min(60, 2 ** min(self.try_count, 6)) * 1000)

    def _poll(self):
        if self.state == "linked":
            self._send(self._poll_packet())
        if self.state in ("linking", "linked") and time.monotonic() - self.last_rx > POLL_TIMEOUT_S:
            self.log.emit(tr("{protocol}: {reflector} does not answer, relinking", protocol=self.NAME, reflector=self.reflector.strip()))
            self.link()

    def _read(self):
        while self.sock.state() == QUdpSocket.BoundState and self.sock.hasPendingDatagrams():
            data = bytes(self.sock.receiveDatagram().data())
            self.last_rx = time.monotonic()
            self._handle(data)

    def _ack(self, data):
        """14-byte ACK/NAK reply to a link request."""
        reply = data[10:13]
        self.try_timer.stop()
        if reply == b"ACK":
            self.log.emit(tr("{protocol}: linked to {reflector}", protocol=self.NAME, reflector=self.reflector.strip()))
            self._set_state("linked")
        else:
            self.log.emit(tr("{protocol}: {reflector} refuses the link ({reply})", protocol=self.NAME, reflector=self.reflector.strip(), reply=reply.decode(errors="replace")))
            self.poll_timer.stop()
            self._set_state("refused")


class DCSLink(_Link):
    NAME = "DCS"
    PORT = DCS_PORT
    POLL_MS = 5000

    def __init__(self, *args):
        super().__init__(*args)
        self.rpt_seq = 0
        self.tx_header = None
        self.rx_ids = set()

    def _link_packet(self):
        pkt = bytearray(519)
        pkt[0:8] = (self.repeater[:7] + " ").encode()
        pkt[8] = ord(self.repeater[7])
        pkt[9] = ord(self.reflector[7])
        pkt[10] = 0
        pkt[11:19] = (self.reflector[:7] + " ").encode()
        html = DCS_HTML.encode()[:500]
        pkt[19:19 + len(html)] = html
        return bytes(pkt)

    def _unlink_packet(self):
        pkt = bytearray(19)
        pkt[0:8] = (self.repeater[:7] + " ").encode()
        pkt[8] = ord(self.repeater[7])
        pkt[9] = 0x20
        pkt[10] = 0
        pkt[11:19] = (self.reflector[:7] + " ").encode()
        return bytes(pkt)

    def _poll_packet(self):
        return self.repeater.encode() + b"\x00" + self.reflector.encode()

    def send_header(self, stream_id, header):
        # DCS has no header packet: every voice packet carries the header
        self.tx_header = header.with_(flag1=0, flag2=0, flag3=0, rpt1=self.repeater, rpt2=self.reflector,
                                      your=pad("CQCQCQ"))
        self.rpt_seq = 0

    def send_data(self, stream_id, seq, frame, end=False):
        if self.state != "linked" or self.tx_header is None:
            return
        pkt = bytearray(100)
        pkt[0:4] = b"0001"
        pkt[4:7] = b"\x00\x00\x00"
        pkt[7:43] = self.tx_header.callsigns()
        struct.pack_into("<H", pkt, 43, stream_id)
        pkt[45] = seq | (0x40 if end else 0)
        # End frame as ircDDBGateway sends it: end pattern, then 0x55 x3 in the slow data bytes
        pkt[46:58] = (END_PATTERN_BYTES[:6] + b"\x00\x00\x00\x55\x55\x55") if end else bytes(frame)
        pkt[58:61] = struct.pack("<I", self.rpt_seq)[:3]
        pkt[61:64] = b"\x01\x00\x21"
        self.rpt_seq += 1
        self._send(bytes(pkt))
        if end:
            self.tx_header = None

    def _handle(self, data):
        n = len(data)
        if n >= 100 and data[0:4] == b"0001":
            stream_id = struct.unpack_from("<H", data, 43)[0]
            if stream_id not in self.rx_ids:
                self.rx_ids = {stream_id}
                h = Header(0, 0, 0, *(data[7 + 8 * i:15 + 8 * i].decode("ascii", "replace") for i in range(4)),
                           my2=data[39:43].decode("ascii", "replace"))
                self.header_received.emit(stream_id, h)
            seq = data[45]
            end = bool(seq & 0x40)
            self.data_received.emit(stream_id, seq & 0x1F, data[46:58], end)
            if end:
                self.rx_ids = set()
        elif n == 14:
            if self.state == "linking":
                self._ack(data)
        elif n == 22:
            # Poll from the reflector: answer it
            self._send(self._poll_packet())
        elif n == 19 and self.state == "linked":
            self.log.emit(tr("{protocol}: {reflector} closed the link", protocol="DCS", reflector=self.reflector.strip()))
            self.poll_timer.stop()
            self._set_state("unlinked")


class DExtraLink(_Link):
    NAME = "DExtra"
    PORT = DEXTRA_PORT
    POLL_MS = 10000

    def _link_packet(self, module=None):
        pkt = bytearray(11)
        pkt[0:8] = (self.repeater[:7] + " ").encode()
        pkt[8] = ord(self.repeater[7])
        pkt[9] = ord(module if module is not None else self.reflector[7])
        pkt[10] = 0
        return bytes(pkt)

    def _unlink_packet(self):
        return self._link_packet(module=" ")

    def _poll_packet(self):
        return (self.repeater[:7] + " ").encode() + b"\x00"

    def send_header(self, stream_id, header):
        if self.state != "linked":
            return
        gateway = self.reflector[:7] + "G"
        h = header.with_(rpt1=gateway, rpt2=self.reflector, your=pad("CQCQCQ"))
        body = b"\x00\x00\x00" + h.callsigns()
        pkt = (b"DSVT\x10\x00\x00\x00\x20\x00\x00\x00" + struct.pack("<H", stream_id) + b"\x80"
               + body + ccitt_crc(body))
        for _ in range(5):
            self._send(pkt)

    def send_data(self, stream_id, seq, frame, end=False):
        if self.state != "linked":
            return
        payload = (NULL_AMBE_DATA_BYTES + END_PATTERN_BYTES[:3]) if end else bytes(frame)
        pkt = (b"DSVT\x20\x00\x00\x00\x20\x00\x00\x00" + struct.pack("<H", stream_id)
               + bytes([seq | (0x40 if end else 0)]) + payload)
        self._send(pkt)

    def _handle(self, data):
        n = len(data)
        if n >= 56 and data[0:4] == b"DSVT" and data[4] == 0x10:
            stream_id = struct.unpack_from("<H", data, 12)[0]
            self.header_received.emit(stream_id, Header.from_radio(data[15:56]))
        elif n >= 27 and data[0:4] == b"DSVT" and data[4] == 0x20:
            stream_id = struct.unpack_from("<H", data, 12)[0]
            seq = data[14]
            self.data_received.emit(stream_id, seq & 0x1F, data[15:27], bool(seq & 0x40))
        elif n == 14 and self.state == "linking":
            self._ack(data)
        elif n == 9:
            return  # keepalive from the reflector
        elif n == 11 and data[9] == 0x20 and self.state == "linked":
            self.log.emit(tr("{protocol}: {reflector} closed the link", protocol="DExtra", reflector=self.reflector.strip()))
            self.poll_timer.stop()
            self._set_state("unlinked")
