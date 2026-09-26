# PyInstaller spec: one-folder build of QDStar (Windows and Linux).
# Build from the repository root:  pyinstaller packaging/qdstar.spec

import sys
from pathlib import Path

root = Path(SPECPATH).parent
pkg = root / "qdstar"

datas = [
    (str(pkg / "icon.svg"), "qdstar"),
    (str(pkg / "default_reflectors.json"), "qdstar"),
    (str(pkg / "fonts"), "qdstar/fonts"),
    (str(pkg / "translations"), "qdstar/translations"),
]

# Qt modules the app does not use: keep the bundle small
excludes = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtQuick3D",
    "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtBluetooth", "PySide6.QtDesigner", "PySide6.QtSql", "PySide6.QtTest", "tkinter",
]

a = Analysis(
    [str(root / "packaging" / "launcher.py")],
    pathex=[str(root)],
    datas=datas,
    hiddenimports=["PySide6.QtSerialPort", "PySide6.QtNetwork", "PySide6.QtSvg", "certifi"],
    excludes=excludes,
)
# Drop Qt libraries/plugins pulled in indirectly that the app never loads
UNUSED = ("Qt6Quick", "Qt6Qml", "Qt6Pdf", "Qt6VirtualKeyboard", "Qt6WebEngine", "Qt63D", "Qt6Multimedia",
          "qtvirtualkeyboard", "qmltooling", "Qt6Designer", "Qt6Charts")
a.binaries = [b for b in a.binaries if not any(u in b[0] for u in UNUSED)]
# Keep only Qt's base translations (qtbase_*.qm); the app's own .po files stay
a.datas = [d for d in a.datas if "PySide6" not in d[0] or "/translations/" not in d[0].replace("\\", "/")
           or "qtbase_" in d[0]]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="qdstar",
    console=False,
    icon=str(root / "packaging" / "qdstar.ico") if sys.platform == "win32" else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="qdstar")
