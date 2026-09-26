"""ircDDBGateway remote control client (UDP), used in EXT mode.

Runs its blocking UDP exchanges in a worker thread and reports through signals.
"""

import hashlib
import queue
import re
import socket
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .qtutil import safe_emit
from .i18n import tr

PROTOCOLS = {0: "DExtra", 1: "DPlus", 2: "DCS", 3: "CCS"}
LINUX_GATEWAY_CONFIG = Path.home() / ".config/dstar/ircddbgateway"
STATUS_PERIOD = 5.0


def pad8(text):
    return text.upper()[:8].ljust(8)


def normalize_reflector(text):
    """'ref001c', 'REF001 C' or 'XLX048A' -> 'REF001 C' (8 chars)."""
    text = re.sub(r"\s+", "", str(text).upper())
    if not re.fullmatch(r"[A-Z0-9]{4,7}[A-Z]", text):
        raise ValueError(tr("Invalid reflector format (e.g. REF001 C)"))
    return text[:-1].ljust(7) + text[-1]


def password_from_config():
    """The Linux ircDDBGateway stack keeps its random remote password in its config file."""
    try:
        match = re.search(r"^remotePassword=(.*)$", LINUX_GATEWAY_CONFIG.read_text(), re.M)
        return match.group(1).strip() if match else ""
    except OSError:
        return ""


class GatewayClient(QObject):
    # reachable, links: [{"reflector", "protocol", "linked", "incoming", "dongle"}]
    status = Signal(bool, list)
    result = Signal(bool, str)   # outcome of link/unlink
    log = Signal(str)

    def __init__(self, host, port, password, repeater):
        super().__init__()
        self.addr = (host, int(port))
        self.password = password or password_from_config()
        self.repeater = pad8(repeater)
        self.sock = None
        self.logged_in = False
        self.jobs = queue.Queue()
        self.stopping = threading.Event()
        self.reachable = None
        self.thread = threading.Thread(target=self._run, daemon=True, name="ircddbgateway")

    # --- public (thread safe) -----------------------------------------------

    def start(self):
        self.thread.start()

    def stop(self):
        self.stopping.set()
        self.jobs.put(None)

    def link(self, reflector):
        self.jobs.put(("link", normalize_reflector(reflector)))

    def unlink(self):
        self.jobs.put(("link", ""))

    def refresh(self):
        self.jobs.put(("status", None))

    # --- worker ---------------------------------------------------------------

    def _run(self):
        while not self.stopping.is_set():
            try:
                job = self.jobs.get(timeout=STATUS_PERIOD)
            except queue.Empty:
                job = ("status", None)
            if job is None:
                break
            kind, arg = job
            if kind == "link":
                try:
                    self._link(arg)
                    safe_emit(self.result, True, arg.strip() or tr("unlinked"))
                except (OSError, RuntimeError) as exc:
                    safe_emit(self.result, False, str(exc))
            self._poll_status()
        if self.sock:
            self.sock.close()

    def _poll_status(self):
        try:
            links = self._status()
            ok = True
        except (OSError, RuntimeError) as exc:
            links, ok = [], False
            if self.reachable is not False:
                safe_emit(self.log, tr("ircDDBGateway does not answer at {host}:{port} ({error})", host=self.addr[0], port=self.addr[1], error=exc))
        if ok and self.reachable is not True:
            safe_emit(self.log, tr("ircDDBGateway connected"))
        self.reachable = ok
        safe_emit(self.status, ok, links)

    def _open(self):
        if self.sock is None:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.settimeout(2.0)

    def _request(self, payload):
        self.sock.sendto(payload, self.addr)
        data, _ = self.sock.recvfrom(4096)
        return data

    def _login(self):
        self._open()
        reply = self._request(b"LIN")
        if reply[:3] != b"RND":
            raise RuntimeError(tr("unexpected login reply"))
        digest = hashlib.sha256(reply[3:7] + self.password.encode()).digest()
        reply = self._request(b"SHA" + digest)
        if reply[:3] != b"ACK":
            raise RuntimeError(reply[3:].split(b"\0")[0].decode(errors="replace") or tr("login refused"))
        self.logged_in = True

    def _call(self, payload):
        for attempt in range(2):
            try:
                if not self.logged_in:
                    self._login()
                reply = self._request(payload)
                if reply[:3] == b"NAK" and b"not logged in" in reply:
                    self.logged_in = False
                    continue
                return reply
            except (OSError, RuntimeError):
                self.logged_in = False
                if self.sock is not None:
                    self.sock.close()
                    self.sock = None
                if attempt == 1:
                    raise
        raise RuntimeError(tr("could not log into the gateway"))

    def _status(self):
        reply = self._call(b"GRP" + self.repeater.encode())
        if reply[:3] != b"RPT":
            raise RuntimeError(reply[3:].split(b"\0")[0].decode(errors="replace"))
        body = reply[3:]
        links = []
        offset = 8 + 4 + 8
        while offset + 24 <= len(body):
            callsign = body[offset:offset + 8].decode(errors="replace")
            proto, linked, direction, dongle = (
                int.from_bytes(body[offset + 8 + 4 * i: offset + 12 + 4 * i], "little") for i in range(4)
            )
            links.append({"reflector": callsign, "protocol": PROTOCOLS.get(proto, str(proto)),
                          "linked": bool(linked), "incoming": direction == 0, "dongle": bool(dongle)})
            offset += 24
        return links

    def _link(self, reflector):
        payload = b"LNK" + self.repeater.encode() + (0).to_bytes(4, "little") + pad8(reflector).encode()
        reply = self._call(payload)
        if reply[:3] != b"ACK":
            raise RuntimeError(reply[3:].split(b"\0")[0].decode(errors="replace"))
