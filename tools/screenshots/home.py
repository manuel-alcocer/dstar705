"""Home page screenshots: the whole window (hero) and the History, D-PRS and Weather views (gallery).

    python3 tools/screenshots/home.py hero en website/site/img        # on the real display
    python3 tools/screenshots/home.py gallery en website/site/img     # offscreen, also with es

Set QDSTAR_SHOT_POS="lat,lon" for distances (only used for them, never shown or stored).
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

mode, lang, out = sys.argv[1], sys.argv[2], os.path.abspath(sys.argv[3])
OWN = "EA7KLX"
data_dir = common.isolate(offscreen=(mode == "gallery"))
common.masked_history(data_dir, OWN)
app = common.qt_app(lang)

from PySide6.QtCore import QPoint, QRect  # noqa: E402
from PySide6.QtWidgets import QTabBar  # noqa: E402
from qdstar import civ, config  # noqa: E402

for key, value in {"radio/auto_connect": False, "updates/check": False, "ui/tray": False, "dstar/mode": "int",
                   "appimage/offer_install": False, "ui/language": lang, "dprs/show_all": True,
                   "dstar/server": "server1.dstar.es", "radio/username": "ic705"}.items():
    config.put(key, value)          # radio/username: without it the settings dialog opens and blocks

from qdstar.mainwindow import MainWindow  # noqa: E402


def pump(secs=0.4):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


w = MainWindow()
w.poller.stop()            # no live data from the reflectors' dashboards (real call signs)
for timer in (w.gps_timer, w.update_timer, w.weather_timer):
    timer.stop()
w.show()
w.resize(420, 875)
pump(1.0)

position = common.own_position()
if position:
    w.own_gps = {"0281": b"\x01", "0287": b"\x01"}
    w.gps_fix = position
w._load_history()
w._load_dprs()
w._load_weather()

rows = w.storage.recent()
rx = [r for r in rows if r["direction"] == "RX"]
candidates = [r for r in rx if r["name"] and r["location"] and r.get("lat") is not None]
if position:
    candidates.sort(key=lambda r: civ.distance_km(*position, r["lat"], r["lon"]) < 500)   # far ones first
on_air = candidates[0] if candidates else rx[0]
heard = [{"callsign": r["callsign"], "name": r["name"] or "", "time": time.strftime("%H:%M:%S", time.localtime(r["started"]))}
         for r in rx[:3]]
item = w.registry.get("/XLX214D") or {}
reflector = {"to": "/XLX214D", "name": item.get("name", "D-STAR Spain"), "description": item.get("description", ""),
             "server": "server1.dstar.es"}
for key in ("radio", "civ", "internet", "reflector", "linked"):
    w.leds[key].set("green")
w.leds["tx"].set("off")


def screen(live):
    info = {"callsign": on_air["callsign"], "suffix": on_air["suffix"], "name": on_air["name"],
            "location": on_air["location"], "message": on_air["message"], "live": live, "started": time.time() - 12}
    if not live:
        info["ended"] = time.time() - 95
    if on_air.get("lat") is not None:
        w._with_position(info, (on_air["lat"], on_air["lon"]))
    w.leds["rx"].set("green" if live else "off")
    # No locator in the footer: it would give our position away
    w.screen.update_state(reflector=reflector, status={"online": True, "users": 10, "linked": True}, to="/XLX214D",
                          rx=info, heard=heard, my_call=f"{OWN} /705", mode="DV", dprs_on=True, locator="",
                          review=None, server_mismatch=False, mode_warning="")


def raise_view(key):
    w.docks[key].raise_()
    pump(0.3)


if mode == "hero":
    screen(True)
    raise_view("history")
    w.grab().save(os.path.join(out, "photo-history.jpg"), "JPG", 88)
    screen(False)
    raise_view("weather")
    w.grab().save(os.path.join(out, "photo-weather.jpg"), "JPG", 88)
    print("hero", w.grab().size().toTuple(), "on air:", on_air["callsign"])
else:
    screen(True)
    bar = next(b for b in w.findChildren(QTabBar) if b.isVisible())
    top = bar.mapTo(w, QPoint(0, 0)).y()
    for key, height in (("history", 420), ("dprs", 250), ("weather", 150)):
        raise_view(key)
        w.grab(QRect(0, top, w.width(), height)).save(os.path.join(out, f"{lang}-tab-{key}.png"))
    print("gallery", lang)
sys.stdout.flush()
os._exit(0)
