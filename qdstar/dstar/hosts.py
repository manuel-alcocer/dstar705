"""Reflector address lookup: Pi-Star host files (kept current) plus the XLX directory."""

import json
import re
import threading
import time

from .. import config
from ..net import http_get

HOST_FILES = {
    "DCS": "http://www.pistar.uk/downloads/DCS_Hosts.txt",
    "DExtra": "http://www.pistar.uk/downloads/DExtra_Hosts.txt",
    "DPlus": "http://www.pistar.uk/downloads/DPlus_Hosts.txt",
}
XLX_API = "http://xlxapi.rlx.lu/api.php?do=GetReflectorList"
REFRESH_S = 24 * 3600


def protocol_for(name):
    """Protocol used to link a reflector: 'REF001' -> DPlus, 'XRF988' -> DExtra, DCS/XLX -> DCS."""
    prefix = name[:3].upper()
    return {"REF": "DPlus", "XRF": "DExtra"}.get(prefix, "DCS")


class HostDirectory:
    def __init__(self):
        self.path = config.data_dir() / "hosts.json"
        self.lock = threading.Lock()
        self.hosts = {"DCS": {}, "DExtra": {}, "DPlus": {}, "XLX": {}}
        self.fetched = 0.0
        try:
            cached = json.loads(self.path.read_text())
            self.hosts.update(cached.get("hosts", {}))
            self.fetched = cached.get("fetched", 0.0)
        except (OSError, ValueError):
            pass

    @staticmethod
    def _get(url):
        return http_get(url, timeout=20)

    def refresh(self, force=False):
        """Blocking download; call from a worker thread."""
        if not force and time.time() - self.fetched < REFRESH_S:
            return True
        fresh = {}
        for proto, url in HOST_FILES.items():
            try:
                text = self._get(url)
            except OSError:
                continue
            table = {}
            for line in text.splitlines():
                parts = line.split()
                if len(parts) >= 2 and not line.startswith("#"):
                    table.setdefault(parts[0].upper(), parts[1])
            fresh[proto] = table
        try:
            xml = self._get(XLX_API)
            fresh["XLX"] = {name.upper(): ip for name, ip in
                            re.findall(r"<name>(\w+)</name>\s*<lastip>([\d.]+)</lastip>", xml)}
        except OSError:
            pass
        if not fresh:
            return False
        with self.lock:
            self.hosts.update(fresh)
            self.fetched = time.time()
            try:
                self.path.write_text(json.dumps({"fetched": self.fetched, "hosts": self.hosts}))
            except OSError:
                pass
        return True

    def lookup(self, name, protocol):
        """Address for 'DCS214' over 'DCS' etc., or None."""
        name = name.upper()
        with self.lock:
            address = self.hosts.get(protocol, {}).get(name)
            if not address and name.startswith(("XLX", "DCS")):
                address = self.hosts.get("XLX", {}).get("XLX" + name[3:])
            return address
