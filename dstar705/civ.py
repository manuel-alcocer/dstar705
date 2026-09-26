"""CI-V framing and IC-705 D-STAR command helpers (IC-705 CI-V reference, pp. 22-23)."""

from dataclasses import dataclass

RADIO_ADDR = 0xA4
CONTROLLER_ADDR = 0xE0

OK = 0xFB
NG = 0xFA


def frame(cmd, sub=b"", data=b"", to=RADIO_ADDR):
    return bytes([0xFE, 0xFE, to, CONTROLLER_ADDR, cmd]) + bytes(sub) + bytes(data) + b"\xFD"


class FrameSplitter:
    """Splits a CI-V byte stream into frames (without preamble/terminator)."""

    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        self.buffer.extend(data)
        frames = []
        while True:
            end = self.buffer.find(0xFD)
            if end < 0:
                break
            raw = bytes(self.buffer[:end])
            del self.buffer[:end + 1]
            start = raw.rfind(b"\xFE\xFE")
            if start >= 0 and len(raw) >= start + 5:
                frames.append(raw[start + 2:])  # to, from, cmd, ...
        if len(self.buffer) > 4096:
            self.buffer.clear()
        return frames


def text8(value):
    return value.upper()[:8].ljust(8).encode("ascii", "replace")


def decode_text(raw):
    if raw and all(b == 0xFF for b in raw):
        return ""
    return raw.decode("ascii", "replace").rstrip()


def raw_callsign(raw):
    """Keep inner spaces (e.g. 'N0CALL Z'); strip only the right padding."""
    if raw and all(b == 0xFF for b in raw):
        return ""
    return raw.decode("ascii", "replace").rstrip()


# --- requests -------------------------------------------------------------

def read_my_call():
    return frame(0x1F, b"\x00")


def read_tx_calls():
    return frame(0x1F, b"\x01")


def set_tx_calls(ur, r1, r2):
    return frame(0x1F, b"\x01", text8(ur) + text8(r1) + text8(r2))


def read_tx_message():
    return frame(0x1F, b"\x02")


def set_tx_message(message):
    return frame(0x1F, b"\x02", message[:20].ljust(20).encode("ascii", "replace"))


def set_auto_rx_output(enabled=True):
    """Enable transceive output of DV RX call signs, message and status."""
    on = b"\x01" if enabled else b"\x00"
    return [frame(0x20, b"\x00\x00", on), frame(0x20, b"\x01\x00", on), frame(0x20, b"\x02\x00", on)]


def read_rx_calls():
    return frame(0x20, b"\x00\x02")


def read_rx_message():
    return frame(0x20, b"\x01\x02")


def read_rx_status():
    return frame(0x20, b"\x02\x02")


def read_frequency():
    return frame(0x03)


def read_mode():
    return frame(0x04)


def read_tx_state():
    return frame(0x1C, b"\x00")


# --- parsed replies -------------------------------------------------------

@dataclass
class RxCalls:
    flags1: int
    flags2: int
    caller: str
    note: str
    called: str
    rpt1: str
    rpt2: str


@dataclass
class RxStatus:
    voice: bool
    last_call_finished: bool
    signal: bool
    bk: bool
    emr: bool
    other_signal: bool
    packet_loss: bool


def bcd_frequency(data):
    freq = 0
    for i, b in enumerate(data[:5]):
        freq += ((b & 0x0F) + 10 * (b >> 4)) * 10 ** (2 * i)
    return freq


MODES = {0x00: "LSB", 0x01: "USB", 0x02: "AM", 0x03: "CW", 0x04: "RTTY", 0x05: "FM", 0x06: "WFM",
         0x07: "CW-R", 0x08: "RTTY-R", 0x17: "DV"}


def parse(body):
    """Parse a frame body (to, from, cmd, ...) into (kind, value) or None."""
    if len(body) < 3:
        return None
    to, src, cmd, rest = body[0], body[1], body[2], body[3:]
    if src != RADIO_ADDR:
        return None  # our own echo or other controllers
    if cmd in (OK, NG):
        return ("ack", cmd == OK)
    if cmd in (0x00, 0x03) and len(rest) >= 5:
        return ("frequency", bcd_frequency(rest))
    if cmd in (0x01, 0x04) and rest:
        return ("mode", MODES.get(rest[0], f"0x{rest[0]:02X}"))
    if cmd == 0x1C and len(rest) >= 2 and rest[0] == 0x00:
        return ("tx", rest[1] == 0x01)
    if cmd == 0x1F and rest:
        sub, data = rest[0], rest[1:]
        if sub == 0x00 and len(data) >= 12:
            return ("my_call", (raw_callsign(data[:8]), decode_text(data[8:12])))
        if sub == 0x01 and len(data) >= 24:
            return ("tx_calls", (raw_callsign(data[:8]), raw_callsign(data[8:16]), raw_callsign(data[16:24])))
        if sub == 0x02:
            return ("tx_message", decode_text(data[:20]))
    if cmd == 0x20 and len(rest) >= 2:
        group, sub, data = rest[0], rest[1], rest[2:]
        if sub not in (0x01, 0x02):
            return None
        if group == 0x00:
            if len(data) >= 38:
                return ("rx_calls", RxCalls(data[0], data[1], raw_callsign(data[2:10]), decode_text(data[10:14]),
                                            raw_callsign(data[14:22]), raw_callsign(data[22:30]),
                                            raw_callsign(data[30:38])))
            return ("rx_calls", None)
        if group == 0x01:
            if len(data) >= 32:
                return ("rx_message", (decode_text(data[:20]), raw_callsign(data[20:28]), decode_text(data[28:32])))
            return ("rx_message", None)
        if group == 0x02 and data:
            b = data[0]
            return ("rx_status", RxStatus(bool(b & 0x40), bool(b & 0x20), bool(b & 0x10), bool(b & 0x08),
                                          bool(b & 0x04), bool(b & 0x02), bool(b & 0x01)))
    return ("other", body.hex(" "))
