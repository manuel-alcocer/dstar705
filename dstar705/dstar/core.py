"""Built-in gateway: routes voice between the radio (USB Terminal Mode) and one reflector link."""

import random
import socket
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal

from ..qtutil import safe_emit

from .dcs import DCSLink, DExtraLink
from .dplus import DPlusAuthenticator, DPlusLink
from .hosts import HostDirectory, protocol_for
from .icom_terminal import IcomTerminal
from .protocol import FRAMES_PER_SUPERFRAME, Header, pad

NET_STREAM_TIMEOUT_MS = 1000


def split_reflector(reflector):
    """'REF001 C' -> ('REF001', 'C')."""
    reflector = pad(reflector)
    return reflector[:7].strip(), reflector[7]


class LocalGateway(QObject):
    log = Signal(str)
    radio_connected = Signal(bool)
    link_changed = Signal(str, str)      # reflector ('' if none), state
    result = Signal(bool, str)           # outcome of a link/unlink request
    status = Signal(bool, list)          # same shape as the ircDDBGateway client: ok, links
    _resolved = Signal(str, str, str)    # reflector, protocol, address ('' if unknown); from a worker thread

    def __init__(self, login, terminal_call, gateway_call, port_name=""):
        super().__init__()
        self.login = login.upper().strip()
        self.terminal_call = pad(terminal_call)
        self.gateway_call = pad(gateway_call)
        self.terminal = IcomTerminal(port_name)
        self.terminal.log.connect(self.log)
        self.terminal.connected.connect(self.radio_connected)
        self.terminal.header_received.connect(self._radio_header)
        self.terminal.data_received.connect(self._radio_data)

        self.auth = DPlusAuthenticator(self.login)
        self.auth.log.connect(self.log)
        self.auth.done.connect(self._auth_done)
        self.pending_link = None

        self.conn = None
        self.reflector = ""
        self.protocol = ""
        self.host_dir = HostDirectory()
        self._resolved.connect(self._on_resolved)
        self.status_timer = QTimer(self, interval=5000)
        self.status_timer.timeout.connect(self.refresh)

        # radio -> network stream
        self.tx_id = 0
        self.tx_seq = 0
        self.radio_tx = False
        # network -> radio stream
        self.rx_id = None
        self.rx_watchdog = QTimer(self, singleShot=True, interval=NET_STREAM_TIMEOUT_MS)
        self.rx_watchdog.timeout.connect(self._net_stream_lost)

    # --- public ---------------------------------------------------------------------

    def start(self):
        self.terminal.open()
        self.auth.start()
        self.status_timer.start()
        self.refresh()

    def stop(self):
        self.status_timer.stop()
        if self.conn:
            self.conn.close()
            self.conn = None
        self.terminal.close()

    def refresh(self):
        links = []
        if self.conn and self.conn.state == "linked":
            links.append({"reflector": self.reflector, "protocol": self.protocol, "linked": True,
                          "incoming": False, "dongle": True})
        self.status.emit(self.terminal.is_connected, links)

    def linked_reflector(self):
        return self.reflector if self.conn and self.conn.state == "linked" else ""

    def link(self, reflector):
        name, _ = split_reflector(reflector)
        protocol = protocol_for(name)
        if protocol == "DPlus" and not self.auth.authenticated_at:
            self.log.emit("DPlus: esperando a la autenticación para enlazar")
            self.pending_link = reflector
            return
        address = self.auth.hosts.get(name) if protocol == "DPlus" else None
        if address:
            self._start_link(reflector, protocol, address)
        else:
            threading.Thread(target=self._resolve, args=(reflector, protocol), daemon=True).start()

    def unlink(self):
        if self.conn:
            self.conn.close()
            self.conn = None
        old, self.reflector = self.reflector, ""
        self.link_changed.emit("", "unlinked")
        self.refresh()
        self.result.emit(True, f"desenlazado de {old.strip()}" if old else "sin enlace")

    # --- linking ----------------------------------------------------------------------

    def _auth_done(self, ok, hosts):
        if self.pending_link:
            reflector, self.pending_link = self.pending_link, None
            if ok:
                self.link(reflector)
            else:
                self.result.emit(False, "No se pudo autenticar en la red DPlus")

    def _resolve(self, reflector, protocol):
        """Worker thread: host files, then DNS for REF reflectors."""
        name, _ = split_reflector(reflector)
        self.host_dir.refresh()
        address = self.host_dir.lookup(name, protocol)
        if not address and protocol == "DPlus":
            try:
                address = socket.gethostbyname(f"{name.lower()}.dstargateway.org")
            except OSError:
                address = None
        if address and not address.replace(".", "").isdigit():
            try:
                address = socket.gethostbyname(address)
            except OSError:
                address = None
        safe_emit(self._resolved, reflector, protocol, address or "")

    def _on_resolved(self, reflector, protocol, address):
        if not address:
            self.result.emit(False, f"{reflector.strip()}: no encuentro su dirección")
            return
        self._start_link(reflector, protocol, address)

    def _start_link(self, reflector, protocol, address):
        if self.conn:
            self.conn.close()
        self.reflector = pad(reflector)
        self.protocol = protocol
        cls = {"DPlus": DPlusLink, "DCS": DCSLink, "DExtra": DExtraLink}[protocol]
        self.conn = cls(self.reflector, address, self.login, self.terminal_call)
        self.conn.log.connect(self.log)
        self.conn.state_changed.connect(self._link_state)
        self.conn.header_received.connect(self._net_header)
        self.conn.data_received.connect(self._net_data)
        self.log.emit(f"{protocol}: enlazando {self.reflector.strip()} ({address})")
        self.conn.link()

    def _link_state(self, state):
        self.link_changed.emit(self.reflector if state == "linked" else "", state)
        self.refresh()
        if state == "linked":
            self.result.emit(True, f"enlazado a {self.reflector.strip()}")
        elif state == "refused":
            self.result.emit(False, f"{self.reflector.strip()} rechaza el enlace")

    # --- radio -> network --------------------------------------------------------------

    def _radio_header(self, header):
        self.radio_tx = True
        self._end_net_stream()          # half duplex: the radio has priority
        self.log.emit(f"TX radio: {header.describe()}")
        if self.conn and self.conn.state == "linked":
            self.tx_id = random.randint(1, 0xFFFF)
            self.tx_seq = 0
            self.conn.send_header(self.tx_id, header.with_(your=pad("CQCQCQ")))

    def _radio_data(self, frame, end):
        if self.conn and self.conn.state == "linked" and self.tx_id:
            if end:
                self.conn.send_data(self.tx_id, self.tx_seq, b"", end=True)
                self.tx_id = 0
            else:
                self.conn.send_data(self.tx_id, self.tx_seq, frame)
                self.tx_seq = (self.tx_seq + 1) % FRAMES_PER_SUPERFRAME
        if end:
            self.radio_tx = False

    # --- network -> radio --------------------------------------------------------------

    def _net_header(self, stream_id, header):
        if self.radio_tx or (self.rx_id is not None and self.rx_id != stream_id):
            return
        if self.rx_id == stream_id:
            return  # repeated header
        self.rx_id = stream_id
        self.log.emit(f"RX {self.reflector.strip()}: {header.describe()}")
        self.terminal.write_header(Header(0, 0, 0, rpt2=self.terminal_call, rpt1=self.gateway_call,
                                          your=pad("CQCQCQ"), my=header.my, my2=header.my2))
        self.rx_watchdog.start()

    def _net_data(self, stream_id, seq, frame, end):
        if stream_id != self.rx_id:
            return
        self.rx_watchdog.start()
        if end:
            self.terminal.write_data(b"", end=True)
            self.rx_id = None
            self.rx_watchdog.stop()
        else:
            self.terminal.write_data(frame)

    def _net_stream_lost(self):
        if self.rx_id is not None:
            self.log.emit("RX: stream de red cortado, cerrando")
            self._end_net_stream()

    def _end_net_stream(self):
        if self.rx_id is not None:
            self.terminal.write_data(b"", end=True)
            self.rx_id = None
            self.rx_watchdog.stop()
