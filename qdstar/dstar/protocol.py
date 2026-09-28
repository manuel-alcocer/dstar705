"""D-STAR constants, header representation and CRC."""

from dataclasses import dataclass, replace

RADIO_HEADER_LENGTH = 41          # 3 flags + 4 x 8 call signs + 4 suffix + 2 CRC
DV_FRAME_LENGTH = 12              # 9 AMBE + 3 slow data
VOICE_FRAME_LENGTH = 9

DATA_SYNC_BYTES = bytes([0x55, 0x2D, 0x16])
END_PATTERN_BYTES = bytes([0x55, 0x55, 0x55, 0x55, 0xC8, 0x7A, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
NULL_AMBE_DATA_BYTES = bytes([0x9E, 0x8D, 0x32, 0x88, 0x26, 0x1A, 0x3F, 0x61, 0xE8])
NULL_SLOW_DATA_BYTES = bytes([0x16, 0x29, 0xF5])
NULL_FRAME = NULL_AMBE_DATA_BYTES + NULL_SLOW_DATA_BYTES
SYNC_FRAME = NULL_AMBE_DATA_BYTES + DATA_SYNC_BYTES

FRAMES_PER_SUPERFRAME = 21        # sequence numbers 0..20, sync on 0

DPLUS_PORT = 20001
DEXTRA_PORT = 30001
DCS_PORT = 30051


def _make_crc_table():
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
        table.append(crc)
    return table


_CRC_TABLE = _make_crc_table()


def ccitt_crc(data):
    """D-STAR header checksum (CRC-16/X.25), returned as the two wire bytes."""
    crc = 0xFFFF
    for b in data:
        crc = (crc >> 8) ^ _CRC_TABLE[(crc ^ b) & 0xFF]
    crc = ~crc & 0xFFFF
    return bytes([crc & 0xFF, crc >> 8])


def pad(call, length=8):
    return call.upper()[:length].ljust(length)


@dataclass(frozen=True)
class Header:
    flag1: int = 0
    flag2: int = 0
    flag3: int = 0
    rpt2: str = "        "
    rpt1: str = "        "
    your: str = "CQCQCQ  "
    my: str = "        "
    my2: str = "    "

    @classmethod
    def from_radio(cls, data):
        """41-byte radio header (flags, RPT2, RPT1, UR, MY, suffix, CRC)."""
        text = data.decode("ascii", "replace")
        return cls(data[0], data[1], data[2], text[3:11], text[11:19], text[19:27], text[27:35], text[35:39])

    def callsigns(self):
        return (pad(self.rpt2) + pad(self.rpt1) + pad(self.your) + pad(self.my) + pad(self.my2, 4)).encode("ascii")

    def to_radio(self, with_crc=True):
        body = bytes([self.flag1, self.flag2, self.flag3]) + self.callsigns()
        return body + (ccitt_crc(body) if with_crc else b"\xFF\xFF")

    def with_(self, **changes):
        return replace(self, **changes)

    def describe(self):
        suffix = f"/{self.my2.strip()}" if self.my2.strip() else ""
        return (f"MY {self.my.rstrip()}{suffix}  UR {self.your.rstrip()}  "
                f"R1 {self.rpt1.rstrip()}  R2 {self.rpt2.rstrip()}")


def is_end_frame(frame):
    return frame[:6] == END_PATTERN_BYTES[:6]


# --- slow data --------------------------------------------------------------------

SLOW_DATA_SCRAMBLER = bytes([0x70, 0x4F, 0x93])
MESSAGE_LENGTH = 20


def scramble(data3):
    return bytes(b ^ s for b, s in zip(data3, SLOW_DATA_SCRAMBLER))


def message_slow_data(text):
    """Slow data of a 20-character text message: 8 scrambled 3-byte pieces (frames 1-8 of a superframe)."""
    text = text.encode("ascii", "replace")[:MESSAGE_LENGTH].ljust(MESSAGE_LENGTH)
    pieces = []
    for block in range(4):
        data = bytes([0x40 | block]) + text[block * 5:block * 5 + 5]
        pieces += [scramble(data[:3]), scramble(data[3:])]
    return pieces


def message_frames(text, superframes=2):
    """Silent DV frames that carry a text message, starting with a sync frame."""
    pieces = message_slow_data(text)
    frames = []
    for n in range(superframes * FRAMES_PER_SUPERFRAME):
        seq = n % FRAMES_PER_SUPERFRAME
        if seq == 0:
            frames.append(SYNC_FRAME)
        elif seq <= len(pieces):
            frames.append(NULL_AMBE_DATA_BYTES + pieces[seq - 1])
        else:
            frames.append(NULL_FRAME)
    return frames


# --- UR commands (ircDDBGateway syntax) -----------------------------------------------

REFLECTOR_PREFIXES = ("REF", "XRF", "DCS", "XLX")
LOCAL_COMMANDS = {"U": "unlink", "I": "info", "E": "echo"}


def ur_command(your):
    """('link', 'XLX214 D') for 'XLX214DL' or 'XLX214 D', ('unlink'|'info'|'echo', '') for '       U/I/E', else None.
    A lone letter typed at the start ('U       ') counts too: no call sign is a single letter."""
    if len(your.strip()) == 1:
        your = your.strip().rjust(8)
    your = pad(your)
    if not your[:7].strip():
        command = LOCAL_COMMANDS.get(your[7])
        return (command, "") if command else None
    if your[:3] in REFLECTOR_PREFIXES and your[3:6].strip():
        if your[7] == "L" and your[6].isalpha():            # 'XLX214DL' (ircDDBGateway)
            return ("link", your[:6].strip().ljust(7) + your[6])
        if your[6] == " " and your[7].isalpha():            # 'XLX214 D', the reflector as written
            return ("link", your[:7] + your[7])
    return None
