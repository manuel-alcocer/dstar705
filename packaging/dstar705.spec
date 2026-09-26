# PyInstaller spec: one-folder build of DStar705 (Windows and Linux).
# Build from the repository root:  pyinstaller packaging/dstar705.spec

import sys
from pathlib import Path

root = Path(SPECPATH).parent
pkg = root / "dstar705"

datas = [
    (str(pkg / "icon.svg"), "dstar705"),
    (str(pkg / "default_reflectors.json"), "dstar705"),
    (str(pkg / "fonts"), "dstar705/fonts"),
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
    hiddenimports=["PySide6.QtSerialPort", "PySide6.QtNetwork", "PySide6.QtSvg"],
    excludes=excludes,
)
# Drop Qt libraries/plugins pulled in indirectly that the app never loads
UNUSED = ("Qt6Quick", "Qt6Qml", "Qt6Pdf", "Qt6VirtualKeyboard", "Qt6WebEngine", "Qt63D", "Qt6Multimedia",
          "qtvirtualkeyboard", "qmltooling", "Qt6Designer", "Qt6Charts")
a.binaries = [b for b in a.binaries if not any(u in b[0] for u in UNUSED)]
# Keep only the Qt translations the UI may use
a.datas = [d for d in a.datas if "/translations/" not in d[0].replace("\\", "/")
           or any(lang in d[0] for lang in ("_es", "_en"))]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="dstar705",
    console=False,
    icon=str(root / "packaging" / "dstar705.ico") if sys.platform == "win32" else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="dstar705")
