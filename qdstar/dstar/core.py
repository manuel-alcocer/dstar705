"""Built-in gateway: routes voice between the radio (USB Terminal Mode) and one reflector link."""

import collections
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
from .protocol import FRAMES_PER_SUPERFRAME, Header, is_end_frame, message_frames, pad, ur_command
from ..i18n import tr

NET_STREAM_TIMEOUT_MS = 1000
FRAME_MS = 20                  # DV frame period, for the streams the gateway plays itself
ECHO_MAX_FRAMES = 60 * 50      # one minute
ECHO_DELAY_MS = 1000
ANNOUNCE_DELAY_MS = 500        # the radio must be back on receive
LINK_ANSWER_MS = 10_000


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
    radio_command = Signal(str, str)     # UR command from the radio: link/unlink/info/echo, reflector
    command_over = Signal(str)           # the radio started an over that carries a UR command (its UR)
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
        # UR commands and the streams the gateway plays to the radio (acknowledgements, echo)
        self.command = None
        self.echo_frames = []
        self.announce_link = ""          # reflector whose link outcome the radio is waiting for
        self.announce_timer = QTimer(self, singleShot=True, interval=LINK_ANSWER_MS)
        self.announce_timer.timeout.connect(self._link_unanswered)
        self.play_queue = collections.deque()
        self.play_timer = QTimer(self, interval=FRAME_MS)
        self.play_timer.timeout.connect(self._play_next)

    # --- public ---------------------------------------------------------------------

    def start(self):
        self.terminal.open()
        self.auth.start()
        self.status_timer.start()
        self.refresh()

    def stop(self):
        self.status_timer.stop()
        self.play_timer.stop()
        self.announce_timer.stop()
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
            self.log.emit(tr("DPlus: waiting for authentication before linking"))
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
        self.result.emit(True, tr("unlinked from {reflector}", reflector=old.strip()) if old else tr("no link"))

    # --- linking ----------------------------------------------------------------------

    def _auth_done(self, ok, hosts):
        if self.pending_link:
            reflector, self.pending_link = self.pending_link, None
            if ok:
                self.link(reflector)
            else:
                self.result.emit(False, tr("Could not authenticate on the DPlus network"))

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
            self.result.emit(False, tr("{reflector}: address not found", reflector=reflector.strip()))
            self._announce_outcome(reflector, "Not found")
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
        self.log.emit(tr("{protocol}: linking {reflector} ({address})", protocol=protocol, reflector=self.reflector.strip(), address=address))
        self.conn.link()

    def _link_state(self, state):
        self.link_changed.emit(self.reflector if state == "linked" else "", state)
        self.refresh()
        if state == "linked":
            self.result.emit(True, tr("linked to {reflector}", reflector=self.reflector.strip()))
            self._announce_outcome(self.reflector, "Linked to")
        elif state == "refused":
            self.result.emit(False, tr("{reflector} refuses the link", reflector=self.reflector.strip()))
            self._announce_outcome(self.reflector, "Refused")

    # --- radio -> network --------------------------------------------------------------

    def _radio_header(self, header):
        self.radio_tx = True
        self._end_net_stream()          # half duplex: the radio has priority
        self._stop_playing()
        self.log.emit(f"TX radio: {header.describe()}")
        self.command = ur_command(header.your)
        if self.command:
            # A command for the gateway, not a transmission for the reflector
            self.command_over.emit(header.your.strip())
            self.echo_frames = []
            self.tx_id = 0
            return
        if self.conn and self.conn.state == "linked":
            self.tx_id = random.randint(1, 0xFFFF)
            self.tx_seq = 0
            self.conn.send_header(self.tx_id, header.with_(your=pad("CQCQCQ")))

    def _radio_data(self, frame, end):
        if self.command:
            if self.command[0] == "echo" and not end and len(self.echo_frames) < ECHO_MAX_FRAMES \
                    and not is_end_frame(frame):
                self.echo_frames.append(bytes(frame))
            if end:
                self.radio_tx = False
                command, self.command = self.command, None
                self._run_command(*command)
            return
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
        if self.play_timer.isActive():
            return          # the gateway is talking to the radio (acknowledgement or echo)
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
            self.log.emit(tr("RX: network stream cut, closing"))
            self._end_net_stream()

    def _end_net_stream(self):
        if self.rx_id is not None:
            self.terminal.write_data(b"", end=True)
            self.rx_id = None
            self.rx_watchdog.stop()

    # --- UR commands ----------------------------------------------------------------------

    def _run_command(self, command, reflector):
        self.radio_command.emit(command, reflector)
        if command == "link":
            self.log.emit(tr("Radio command: link {reflector}", reflector=reflector.strip()))
            if pad(reflector) == self.linked_reflector():
                self._announce(f"Linked to {reflector.strip()}")
                self.result.emit(True, tr("linked to {reflector}", reflector=reflector.strip()))
                return
            self.announce_link = pad(reflector)
            self.announce_timer.start()
            self.link(reflector)
        elif command == "unlink":
            self.log.emit(tr("Radio command: unlink"))
            linked = bool(self.linked_reflector())
            self.unlink()
            self._announce("Unlinked" if linked else "Not linked")
        elif command == "info":
            linked = self.linked_reflector()
            self._announce(f"Linked to {linked.strip()}" if linked else "Not linked")
        elif command == "echo":
            frames, self.echo_frames = self.echo_frames, []
            self.log.emit(tr("Radio command: echo test ({seconds:.1f} s)", seconds=len(frames) * FRAME_MS / 1000))
            if frames:
                QTimer.singleShot(ECHO_DELAY_MS, lambda: self._play(frames, "ECHO"))

    def _announce_outcome(self, reflector, text):
        """Tell the radio how the link it asked for ended (links from the window are not announced)."""
        if self.announce_link and pad(reflector) == self.announce_link:
            self.announce_link = ""
            self.announce_timer.stop()
            self._announce(f"{text} {reflector.strip()}")

    def _link_unanswered(self):
        if self.announce_link:
            self._announce_outcome(self.announce_link, "No answer")

    def _announce(self, text):
        QTimer.singleShot(ANNOUNCE_DELAY_MS, lambda: self._play(message_frames(text), "INFO"))

    def _play(self, frames, suffix):
        """Play a stream of our own to the radio, from the gateway call sign, paced like live audio."""
        if self.radio_tx or not self.terminal.is_connected:
            return
        self._end_net_stream()
        self._stop_playing()
        # UR CQCQCQ like the reflector streams: with UR = its own call sign the IC-705 buffers
        # the stream without playing it, then refuses every frame (and stays busy)
        your = pad("CQCQCQ")
        self.terminal.write_header(Header(0, 0, 0, rpt2=self.terminal_call, rpt1=self.gateway_call,
                                          your=your, my=self.gateway_call, my2=pad(suffix, 4)))
        self.play_queue.extend(frames)
        self.play_timer.start()

    def _play_next(self):
        if self.play_queue:
            self.terminal.write_data(self.play_queue.popleft())
        else:
            self._stop_playing()

    def _stop_playing(self):
        if self.play_timer.isActive():
            self.play_timer.stop()
            self.play_queue.clear()
            self.terminal.write_data(b"", end=True)
