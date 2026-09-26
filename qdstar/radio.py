"""High-level IC-705 D-STAR state on top of the network CI-V stream."""

import time

from PySide6.QtCore import QObject, QTimer, Signal

from . import civ
from .icom_udp import IcomConnection
from .i18n import tr

FAST_POLL = 700       # ms: RX status and TX state
SLOW_POLL = 5000      # ms: call sign settings (can be changed on the radio itself)
CIV_ALIVE = 3.0       # s: CI-V answers within this time light the CI-V LED
RX_END_GRACE = 1.5    # s without voice before an RX is considered finished


def kind_of(parsed):
    return parsed[0]


class Radio(QObject):
    log = Signal(str)
    link_state = Signal(str)            # disconnected / connecting / authenticated / connected
    civ_alive = Signal(bool)
    my_call = Signal(str, str)          # call, note
    tx_calls = Signal(str, str, str)    # ur (TO), r1, r2
    tx_message = Signal(str)
    mode = Signal(str)
    transmitting = Signal(bool)
    rx_started = Signal(object)         # civ.RxCalls
    rx_message = Signal(str, str)       # message, caller
    rx_ended = Signal()
    to_write_result = Signal(bool, str)
    raw = Signal(str)                   # changed RX/TX related frames, for the debug log
    setting_received = Signal(str, bytes)   # '0287', data
    dprs_received = Signal(object)          # civ.DprsPosition

    def __init__(self, host, username, password, control_port=50001):
        super().__init__()
        self.conn = IcomConnection(host, username, password, control_port)
        self.conn.log.connect(self.log)
        self.conn.state_changed.connect(self._on_state)
        self.conn.civ_received.connect(self._on_data)
        self.splitter = civ.FrameSplitter()

        self.last_civ = 0.0
        self.civ_ok = False
        self.cur_tx_calls = ("", "", "")
        self.cur_my = ("", "")
        self.cur_mode = ""
        self.is_tx = False
        self.rx_active = False
        self.rx_caller = ""
        self.rx_last_voice = 0.0
        self.rx_voice_seen = False
        self.last_header = None         # last RX header read from the radio (baseline)
        self.last_message = None
        self.rx_message_sent = False
        self.last_dprs = None
        self.last_raw = {}
        self.pending_to = None

        self.fast = QTimer(self, interval=FAST_POLL)
        self.fast.timeout.connect(self._poll_fast)
        self.slow = QTimer(self, interval=SLOW_POLL)
        self.slow.timeout.connect(self._poll_slow)

    # --- public --------------------------------------------------------

    def start(self):
        self.conn.auto_reconnect = True
        self.conn.connect_radio()

    def stop(self):
        self.fast.stop()
        self.slow.stop()
        self.conn.disconnect_radio()

    def set_to(self, to):
        """Write UR (TO), keeping R1/R2 as the radio has them in Terminal Mode.
        In EXT mode the TO is CQCQCQ and the gateway does the linking."""
        ur, r1, r2 = self.cur_tx_calls
        if not r1:
            self.to_write_result.emit(False, tr("R1/R2 have not been read from the radio yet"))
            return
        self.pending_to = to
        self._send(civ.set_tx_calls(to, r1, r2))
        QTimer.singleShot(400, lambda: self._send(civ.read_tx_calls()))
        QTimer.singleShot(3000, self._check_to_written)

    def read_setting(self, number):
        self._send(civ.read_setting(number))

    def write_setting(self, number, data):
        self._send(civ.write_setting(number, data))

    def set_tx_message(self, text):
        self._send(civ.set_tx_message(text))
        QTimer.singleShot(400, lambda: self._send(civ.read_tx_message()))

    # --- internals -----------------------------------------------------

    def _send(self, frame):
        return self.conn.send_civ(frame)

    def _on_state(self, state):
        self.link_state.emit(state)
        if state == "connected":
            for frame in civ.set_auto_rx_output(True):
                self._send(frame)
            self._send(civ.auto_dprs_output(True))
            for frame in (civ.read_mode(), civ.read_my_call(), civ.read_tx_calls(), civ.read_tx_message(),
                          civ.read_rx_status()):
                self._send(frame)
            self.fast.start()
            self.slow.start()
        else:
            self.fast.stop()
            self.slow.stop()
            self._set_civ(False)
            if self.rx_active:
                self._end_rx()

    def _poll_fast(self):
        # Over the network the radio does not push DV RX data (transceive),
        # so the RX header, message and status are polled.
        for frame in (civ.read_tx_state(), civ.read_rx_status(), civ.read_rx_calls(), civ.read_rx_message()):
            self._send(frame)
        self._set_civ(time.monotonic() - self.last_civ < CIV_ALIVE)
        if self.rx_active and time.monotonic() - self.rx_last_voice > RX_END_GRACE:
            self._end_rx()

    def _poll_slow(self):
        for frame in (civ.read_mode(), civ.read_my_call(), civ.read_tx_calls()):
            self._send(frame)

    def _set_civ(self, ok):
        if ok != self.civ_ok:
            self.civ_ok = ok
            self.civ_alive.emit(ok)

    def _check_to_written(self):
        if self.pending_to is None:
            return
        to, self.pending_to = self.pending_to, None
        self.to_write_result.emit(False, tr("The radio did not confirm the TO {to}", to=to))

    def _end_rx(self):
        self.rx_active = False
        self.rx_ended.emit()
        self._send(civ.read_rx_dprs_position())

    def _start_rx(self, header):
        self.rx_message_sent = False
        if self.rx_active:
            self._end_rx()
        self.rx_active = True
        self.rx_caller = header.caller
        self.rx_last_voice = time.monotonic()
        self.rx_started.emit(header)
        # D-PRS rides in the slow data: ask for the received position once it has arrived
        QTimer.singleShot(2500, lambda: self._send(civ.read_rx_dprs_position()))

    def _on_header(self, header):
        if header is None:
            return
        first = self.last_header is None
        changed = header != self.last_header
        self.last_header = header
        if first:
            return  # whatever was heard before we connected
        if changed and header.caller:
            self._start_rx(header)

    def _on_data(self, data):
        for body in self.splitter.feed(data):
            parsed = civ.parse(body)
            if not parsed:
                continue
            if body[2] in (0x1C, 0x20):
                key = bytes(body[2:5])
                if self.last_raw.get(key) != body:
                    self.last_raw[key] = body
                    self.raw.emit(f"{kind_of(parsed)} {body.hex(' ')}")
            self.last_civ = time.monotonic()
            self._set_civ(True)
            kind, value = parsed
            if kind == "my_call" and value != self.cur_my:
                self.cur_my = value
                self.my_call.emit(*value)
            elif kind == "tx_calls":
                if value != self.cur_tx_calls:
                    self.cur_tx_calls = value
                    self.tx_calls.emit(*value)
                if self.pending_to is not None and value[0] == self.pending_to:
                    self.to_write_result.emit(True, self.pending_to)
                    self.pending_to = None
            elif kind == "tx_message":
                self.tx_message.emit(value)
            elif kind == "mode" and value != self.cur_mode:
                self.cur_mode = value
                self.mode.emit(value)
            elif kind == "tx" and value != self.is_tx:
                self.is_tx = value
                self.transmitting.emit(value)
            elif kind == "rx_calls":
                self._on_header(value)
            elif kind == "rx_message":
                # Deliver the message once per over, even when it equals the previous one
                if value is not None and self.rx_active and not self.rx_message_sent and \
                        value[1].split()[:1] == self.rx_caller.split()[:1]:
                    self.rx_message_sent = True
                    self.last_message = value
                    self.rx_message.emit(value[0], value[1])
                elif value is not None and value != self.last_message:
                    first = self.last_message is None
                    self.last_message = value
                    if not first:
                        self.rx_message.emit(value[0], value[1])
            elif kind == "rx_status":
                if value.voice:
                    self.rx_last_voice = time.monotonic()
                    self.rx_voice_seen = True
                    if not self.rx_active and self.last_header is not None:
                        # A new over with the same header as the previous one
                        self._start_rx(self.last_header)
            elif kind == "setting":
                self.setting_received.emit(*value)
            elif kind == "dprs" and value is not None:
                # The radio keeps the last position it heard: only pass on new data, or data
                # from the station on air (a read may return an earlier station's position)
                raw = bytes(body[3:])
                caller = self.rx_caller.split()[:1]
                if raw != self.last_dprs or value.callsign.split("-")[0].split()[:1] == caller:
                    self.last_dprs = raw
                    self.dprs_received.emit(value)
            elif kind == "ack" and not value:
                pass  # e.g. frequency reads are refused in Terminal Mode
