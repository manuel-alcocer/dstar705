"""CI-V framing and IC-705 D-STAR command helpers (IC-705 CI-V reference, pp. 22-23)."""

from dataclasses import dataclass

from .i18n import N_, tr

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
    if cmd == 0x1A and len(rest) >= 3 and rest[0] == 0x05:
        return ("setting", (rest[1:3].hex(), bytes(rest[3:])))
    if cmd == 0x20 and len(rest) >= 2 and rest[0] == 0x03:
        if rest[1] in (0x01, 0x02):
            return ("dprs", parse_dprs_position(bytes(rest[2:])))
        return None
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


# --- settings (1A 05 nnnn) ------------------------------------------------

def read_setting(number):
    """number: 4-digit string, e.g. '0287'."""
    return frame(0x1A, b"\x05" + bytes.fromhex(number))


def write_setting(number, data):
    return frame(0x1A, b"\x05" + bytes.fromhex(number), bytes(data))


def auto_dprs_output(enabled=True):
    return frame(0x20, b"\x03\x00", b"\x01" if enabled else b"\x00")


def read_rx_dprs_position():
    """Last received GPS/D-PRS data. The reply carries the data type (position/object/item/weather)."""
    return frame(0x20, b"\x03\x02")


# --- positions (IC-705 CI-V reference, "Manually entered position data" and "GPS/D-PRS data") ---

def _digits(data):
    out = []
    for b in data:
        out += [b >> 4, b & 0x0F]
    return out


def _bcd(digits):
    return bytes((digits[i] << 4) | digits[i + 1] for i in range(0, len(digits), 2))


def decode_latitude(data):
    """5 bytes dd mm.mmm + N/S -> signed degrees, or None."""
    if len(data) < 5 or data[:5] == b"\xFF" * 5:
        return None
    d = _digits(data[:5])
    value = d[0] * 10 + d[1] + (d[2] * 10 + d[3] + d[4] / 10 + d[5] / 100 + d[6] / 1000) / 60
    return value if d[9] == 1 else -value


def decode_longitude(data):
    """6 bytes ddd mm.mmm + E/W -> signed degrees, or None."""
    if len(data) < 6 or data[:6] == b"\xFF" * 6:
        return None
    d = _digits(data[:6])
    value = d[1] * 100 + d[2] * 10 + d[3] + (d[4] * 10 + d[5] + d[6] / 10 + d[7] / 100 + d[8] / 1000) / 60
    return value if d[11] == 1 else -value


def decode_altitude(data):
    """4 bytes, 0.1 m steps + sign -> metres, or None."""
    if len(data) < 4 or data[:4] == b"\xFF" * 4:
        return None
    d = _digits(data[:4])
    value = (d[0] * 10000 + d[1] * 1000 + d[2] * 100 + d[3] * 10 + d[4] + d[5] / 10)
    return -value if d[7] == 1 else value


def _minutes_digits(value):
    """Absolute degrees -> (whole degrees, [m10, m1, m0.1, m0.01, m0.001])."""
    thousandths = round(abs(value) * 60000)       # minutes * 1000
    deg, rest = divmod(thousandths, 60000)
    return deg, [int(c) for c in f"{rest:05d}"]


def encode_position(lat, lon, alt=None):
    """Manual Position (1A 05 0286) payload: latitude, longitude and altitude."""
    deg, m = _minutes_digits(lat)
    lat_bytes = _bcd([deg // 10, deg % 10, *m, 0, 0, 1 if lat >= 0 else 0])
    deg, m = _minutes_digits(lon)
    lon_bytes = _bcd([0, deg // 100, (deg // 10) % 10, deg % 10, *m, 0, 0, 1 if lon >= 0 else 0])
    if alt is None:
        alt_bytes = b"\xFF\xFF\xFF\xFF"
    else:
        tenths = min(round(abs(alt) * 10), 999999)
        alt_bytes = _bcd([int(c) for c in f"{tenths:06d}"] + [0, 1 if alt < 0 else 0])
    return lat_bytes + lon_bytes + alt_bytes


DPRS_KINDS = {0x00: "position", 0x01: "object", 0x02: "item", 0x03: "weather"}


@dataclass
class DprsPosition:
    callsign: str      # 'EA7JTR-7' (for objects and items: their name)
    symbol: str        # '/['
    lat: float
    lon: float
    altitude: float = None
    kind: str = "position"


def parse_dprs_position(data):
    """GPS/D-PRS data after '20 03 01' (transceive) or '20 03 02' (read):
    data type (00 position, 01 object, 02 item, 03 weather), then the name (9),
    symbol (2), latitude (5) and longitude (6), as in the IC-705 CI-V reference."""
    if len(data) < 1 + 9 + 2 + 5 + 6 or data[0] not in DPRS_KINDS or data[1:10] == b"\xFF" * 9:
        return None
    body = data[1:]
    lat = decode_latitude(body[11:16])
    lon = decode_longitude(body[16:22])
    if lat is None or lon is None or (abs(lat) < 1e-6 and abs(lon) < 1e-6):
        return None   # no position; 0°,0° is what radios without a GPS fix send
    return DprsPosition(body[0:9].decode("ascii", "replace").strip(),
                        body[9:11].decode("ascii", "replace"), lat, lon,
                        decode_altitude(body[22:26]) if len(body) >= 26 else None, DPRS_KINDS[data[0]])


def locator_to_latlon(locator):
    """Maidenhead locator (4 or 6 characters) -> centre of the square."""
    loc = locator.strip().upper()
    if len(loc) not in (4, 6) or not (loc[0:2].isalpha() and loc[2:4].isdigit()):
        raise ValueError(tr("Invalid locator (e.g. IN80DK)"))
    lon = (ord(loc[0]) - 65) * 20 - 180 + int(loc[2]) * 2
    lat = (ord(loc[1]) - 65) * 10 - 90 + int(loc[3])
    if len(loc) == 6:
        lon += (ord(loc[4]) - 65) * 5 / 60 + 2.5 / 60
        lat += (ord(loc[5]) - 65) * 2.5 / 60 + 1.25 / 60
    else:
        lon += 1
        lat += 0.5
    return lat, lon


def distance_km(lat1, lon1, lat2, lon2):
    from math import asin, cos, radians, sin, sqrt
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(a))


def bearing_deg(lat1, lon1, lat2, lon2):
    """Initial great-circle bearing from point 1 to point 2, 0-360 degrees (0 = north)."""
    from math import atan2, cos, degrees, radians, sin
    phi1, phi2, dlon = radians(lat1), radians(lat2), radians(lon2 - lon1)
    x = sin(dlon) * cos(phi2)
    y = cos(phi1) * sin(phi2) - sin(phi1) * cos(phi2) * cos(dlon)
    return (degrees(atan2(x, y)) + 360) % 360


COMPASS_POINTS = (N_("N"), N_("NNE"), N_("NE"), N_("ENE"), N_("E"), N_("ESE"), N_("SE"), N_("SSE"),
                  N_("S"), N_("SSW"), N_("SW"), N_("WSW"), N_("W"), N_("WNW"), N_("NW"), N_("NNW"))


def compass_point(bearing):
    """16-point compass name (English letters; translated for display)."""
    return COMPASS_POINTS[int((bearing + 11.25) // 22.5) % 16]


def latlon_to_locator(lat, lon):
    """Maidenhead locator (6 characters) of a position, e.g. 'IN80DK'."""
    lon += 180
    lat += 90
    return (chr(65 + int(lon // 20)) + chr(65 + int(lat // 10))
            + str(int(lon % 20 // 2)) + str(int(lat % 10))
            + chr(65 + int(lon % 2 * 12)) + chr(65 + int(lat % 1 * 24)))
