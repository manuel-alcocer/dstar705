"""HTTP(S) downloads with a bundled CA list.

A fresh Windows install does not ship every root certificate until a browser asks
for it, so Python's default context fails on sites like radioid.net. certifi's CA
bundle makes HTTPS behave the same on every OS.
"""

import ssl
import urllib.request

from . import __version__

USER_AGENT = f"QDStar/{__version__} (+https://github.com/manuel-alcocer/qdstar)"

try:
    import certifi
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:          # running from source without certifi: use the OS store
    _SSL_CONTEXT = ssl.create_default_context()


def http_get(url, timeout=10, limit=5_000_000):
    """GET a URL and return its body as text."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp:
        return resp.read(limit).decode("utf-8", "replace")
