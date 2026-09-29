"""Shared set-up for the website screenshots: an isolated QDStar with throw-away settings and
data, and a masked copy of the user's history (other stations' call signs cut, no locators).

Nothing is written to the real settings or data. Our own position is never stored here: pass
it in QDSTAR_SHOT_POS="lat,lon" only to get distances in the images (it is never shown).
"""

import os
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REAL_DATA = Path.home() / ".local/share/QDStar/QDStar"

CALL = re.compile(r"\b(?:[A-Z]{1,2}|\d[A-Z])\d{1,2}[A-Z]{1,4}\b")
LOC = re.compile(r"\b[A-Ra-r]{2}\d{2}(?:[A-Xa-x]{2})?\b")


def isolate(offscreen):
    """Temporary XDG dirs (before Qt starts) and the repository on sys.path."""
    if offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
    data_home = tempfile.mkdtemp()
    os.environ["XDG_DATA_HOME"] = data_home
    sys.path.insert(0, str(REPO))
    os.chdir(REPO)
    data = Path(data_home) / "QDStar" / "QDStar"
    data.mkdir(parents=True)
    return data


def mask_call(call, own):
    if not call:
        return call
    base, sep, ssid = call.partition("-")
    base = base.strip()
    if base.upper() == own:
        return call
    return base[:3] + "…" + (sep + ssid if sep else "")


def mask_text(text, own):
    if not text:
        return text
    if any(ord(c) < 32 or c == "�" for c in text.strip()) or "%" in text or "@" in text:
        return ""                                            # radio garbage
    if text.startswith(("Linked to", "Unlinked", "Not linked")):
        return ""                                            # gateway acknowledgements
    text = LOC.sub("", text)                                 # locators first (IM88EC is not a call sign)
    text = re.sub(r"DME:\S+", "", text)
    text = CALL.sub(lambda m: m.group(0) if m.group(0).upper() == own else m.group(0)[:3] + "…", text)
    return " ".join(text.split())


def masked_history(data_dir, own):
    """Copy of the real history into data_dir/qdstar.db with other stations masked."""
    target = data_dir / "qdstar.db"
    shutil.copy(REAL_DATA / "qdstar.db", target)
    db = sqlite3.connect(target)
    for i, call, message in db.execute("select id, callsign, message from history").fetchall():
        db.execute("update history set callsign = ?, message = ? where id = ?",
                   (mask_call(call, own), mask_text(message, own), i))
    for i, name, via in db.execute("select id, name, via from dprs").fetchall():
        db.execute("update dprs set name = ?, via = ? where id = ?", (mask_call(name, own), mask_call(via, own), i))
    db.execute("delete from dprs where upper(name) like ?", (own + "%",))    # our own beacon
    db.execute("delete from names")                                         # other stations' cache
    db.commit()
    db.close()


def own_position():
    value = os.environ.get("QDSTAR_SHOT_POS", "")
    try:
        lat, lon = (float(v) for v in value.split(","))
        return lat, lon
    except ValueError:
        return None


def qt_app(lang):
    from PySide6.QtCore import QLibraryInfo, QTranslator
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    app.setOrganizationName("QDStar")
    app.setApplicationName("QDStar")
    app.setWindowIcon(QIcon(str(REPO / "qdstar/icon.svg")))
    from qdstar import i18n
    i18n.set_language(lang)
    translator = QTranslator(app)
    if lang != "en" and translator.load(f"qtbase_{lang}", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(translator)
    app._translator = translator
    return app
