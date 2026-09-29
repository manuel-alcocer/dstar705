"""Manual screenshots, offscreen, with generic values and made-up data (no real data at all).

    python3 tools/screenshots/manual.py en website/site/img
    python3 tools/screenshots/manual.py es website/site/img
"""

import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

lang, out = sys.argv[1], os.path.abspath(sys.argv[2])
common.isolate(offscreen=True)
app = common.qt_app(lang)
en = lang == "en"

from qdstar import config, sources  # noqa: E402
from qdstar.widgets import ReflectorScreen, load_fonts  # noqa: E402

load_fonts()
config.put("radio/username", "ic705")
config.put("dstar/server", "server1.dstar.es")
config.put("aprs/enabled", True)

from qdstar.dialogs import ReflectorsDialog, SettingsDialog, SourcesDialog  # noqa: E402
from qdstar.reflectors import Registry  # noqa: E402


def pump(n=50):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.01)


# Settings, one image per tab
dialog = SettingsDialog(None, my_note=None)
dialog.show()
for i, name in enumerate(("interface", "radio", "modes", "aprs")):
    dialog.tabs.setCurrentIndex(i)
    dialog.adjustSize()
    app.processEvents()
    dialog.grab().save(f"{out}/{lang}-settings-{name}.png")
dialog.close()

# The screen showing an over from the history
screen = ReflectorScreen()
screen.resize(480, 360)
now = time.time()
screen.update_state(
    reflector={"name": "D-STAR Spain", "to": "/XLX214D", "server": "server1.dstar.es", "description": "XLX214/DCS214 D"},
    status={"online": True, "users": 10, "linked": True}, my_call="EA7KLX /705", locator="", mode="DV", dprs_on=True,
    heard=[{"callsign": "ED2…", "name": "", "time": "06:45"}, {"callsign": "EA7…", "name": "Jesus", "time": "06:39"},
           {"callsign": "EA7KLX", "name": "Manuel", "time": "06:38"}],
    review={"callsign": "EA4…", "suffix": "705", "name": "Javi", "location": "Móstoles", "message": "Mostoles Javi",
            "started": now - 5400, "ended": now - 5385, "direction": "RX", "reflector": "/XLX214D",
            "pos": (40.3, -3.87), "distance": 379, "bearing": 28})
screen.show()
app.processEvents()
screen.grab().save(f"{out}/{lang}-screen-history.png")

# Reflector manager and sources, with made-up sources
work = tempfile.mkdtemp()
with open(f"{work}/club.json", "w") as f:
    json.dump([{"via": "ext", "to": "XLX777 B", "name": "Radio club" if en else "Radioclub"},
               {"via": "ext", "to": "DCS777 C", "name": "Club net" if en else "Red del club"}], f)
registry = Registry()
manager = registry.sources
club = sources.new_source("file")
club.update(name="Radio club list" if en else "Lista del radioclub", location=f"{work}/club.json")
repo = sources.new_source("git")
repo.update(name="Club repository" if en else "Repositorio del club",
            location="https://git.example.org/club/reflectors.git", username="club")
url = sources.new_source("url")
url.update(location="https://example.org/reflectors.json", enabled=False)
manager.set_sources(manager.sources() + [club, repo, url])
manager.refresh(club["id"])
pump()
manager.status[repo["id"]] = {"ok": True, "count": 12, "when": now - 3600, "message": ""}   # not fetched for real
registry.upsert({"via": "ext", "to": "XLX999 A", "name": "My reflector" if en else "Mi reflector"})
reflectors = ReflectorsDialog(registry, "ext")
reflectors.show()
app.processEvents()
for i in range(reflectors.list.count()):
    if "REF001" in reflectors.list.item(i).text():
        reflectors.list.setCurrentRow(i)
app.processEvents()
reflectors.grab().save(f"{out}/{lang}-reflectors.png")
dialog = SourcesDialog(registry)
dialog.show()
app.processEvents()
dialog.grab().save(f"{out}/{lang}-sources.png")
print("manual", lang, "settings/screen-history/reflectors/sources")
sys.stdout.flush()
os._exit(0)
