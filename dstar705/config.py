"""Persistent settings (QSettings) and data paths."""

import sys
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths

ORG = "DStar705"
APP = "DStar705"

DEFAULTS = {
    "radio/host": "",
    "radio/username": "",
    "radio/password": "",
    "radio/control_port": 50001,
    "radio/auto_connect": True,
    # Gateway Repeater (Server/IP/Domain) configured in the radio's DV GW menu.
    # CI-V cannot read it, so the user states it here.
    "dstar/server": "",
    # INT = Terminal Mode, internal gateway over WiFi (G3 servers)
    # EXT = Terminal Mode, external gateway over USB (DStarRepeater + ircDDBGateway on the PC)
    "dstar/mode": "int",
    # Station call sign: taken from the radio's MY call sign when empty
    "station/callsign": "",
    # Terminal/AP call signs; empty = call sign + Z (INT) / B (EXT)
    "int/terminal_call": "",
    "ext/terminal_call": "",
    # builtin = DStar705's own gateway (USB Terminal Mode + DPlus); ircddbgateway = external G4KLX stack
    "ext/backend": "builtin",
    "ext/usb_port": "",          # empty: auto-detect the IC-705 data port
    "ext/gateway_host": "127.0.0.1",
    "ext/gateway_port": 54321,
    "ext/gateway_password": "",  # empty: read from the Linux ircDDBGateway config
    "ext/start_cmd": "systemctl --user start dstar.target" if sys.platform.startswith("linux") else "",
    # Run when the radio's USB appears: DStarRepeater cannot open a port that was absent at start-up
    "ext/usb_cmd": "systemctl --user restart dstarrepeater" if sys.platform.startswith("linux") else "",
    "ext/stop_cmd": "systemctl --user stop dstar.target" if sys.platform.startswith("linux") else "",
    "ui/geometry": None,
    "ui/debug_civ": True,
}


def settings():
    return QSettings(ORG, APP)


def get(key):
    value = settings().value(key, DEFAULTS.get(key))
    default = DEFAULTS.get(key)
    if isinstance(default, bool):
        return value in (True, "true", "1", 1)
    if isinstance(default, int) and value is not None:
        return int(value)
    return value


def put(key, value):
    settings().setValue(key, value)


def data_dir():
    path = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))
    path.mkdir(parents=True, exist_ok=True)
    return path


def import_wfview_credentials():
    """On first run, reuse the radio address and login stored by wfview, if any."""
    if get("radio/username"):
        return False
    candidates = [
        Path.home() / ".config/wfview/wfview.conf",           # Linux
        Path.home() / "AppData/Roaming/wfview/wfview.ini",    # Windows (ini variant)
    ]
    for path in candidates:
        if path.exists():
            wf = QSettings(str(path), QSettings.IniFormat)
            user = wf.value("LAN/Username")
            if user:
                put("radio/host", wf.value("LAN/IPAddress", DEFAULTS["radio/host"]))
                put("radio/username", user)
                put("radio/password", wf.value("LAN/Password", ""))
                put("radio/control_port", int(wf.value("LAN/ControlLANPort", 50001)))
                return True
    return False


def callsign():
    return (get("station/callsign") or "").upper().strip()


def terminal_call(mode):
    """Terminal/AP call sign the radio uses in INT or EXT mode, e.g. 'N0CALL B'."""
    configured = (get(f"{mode}/terminal_call") or "").upper().strip()
    if configured:
        return configured.ljust(8)[:8]
    call = callsign()
    return (call.ljust(7)[:7] + ("Z" if mode == "int" else "B")) if call else ""


def gateway_call():
    call = callsign()
    return (call.ljust(7)[:7] + "G") if call else ""

