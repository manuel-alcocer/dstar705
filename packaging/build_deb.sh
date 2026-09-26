#!/bin/sh
# Build a .deb from the PyInstaller one-folder output.
# Usage: packaging/build_deb.sh <version> <deb-arch: amd64|arm64>
set -eu
VERSION="$1"
ARCH="$2"
ROOT="build/deb/qdstar_${VERSION}_${ARCH}"
rm -rf "$ROOT"
mkdir -p "$ROOT/DEBIAN" "$ROOT/opt" "$ROOT/usr/bin" \
         "$ROOT/usr/share/applications" "$ROOT/usr/share/icons/hicolor/256x256/apps"
cp -a dist/qdstar "$ROOT/opt/qdstar"
ln -s /opt/qdstar/qdstar "$ROOT/usr/bin/qdstar"
cp packaging/qdstar.desktop "$ROOT/usr/share/applications/"
cp packaging/qdstar.png "$ROOT/usr/share/icons/hicolor/256x256/apps/"
cat > "$ROOT/DEBIAN/control" <<CONTROL
Package: qdstar
Version: ${VERSION}
Section: hamradio
Priority: optional
Architecture: ${ARCH}
Depends: libegl1, libgl1, libfontconfig1, libxkbcommon-x11-0, libxcb-cursor0, libxcb-icccm4, libxcb-keysyms1, libxcb-shape0, libdbus-1-3
Replaces: dstar705
Conflicts: dstar705
Provides: dstar705
Maintainer: Manuel Alcocer Jiménez (EA7KLX) <24668452+manuel-alcocer@users.noreply.github.com>
Homepage: https://github.com/manuel-alcocer/qdstar
Description: Icom IC-705 D-STAR Terminal Mode controller and gateway
 Controls the IC-705 over WiFi (Icom network protocol) and links reflectors
 (REF/DPlus, DCS, XLX, XRF/DExtra) through its built-in USB Terminal Mode gateway.
CONTROL
dpkg-deb --root-owner-group --build "$ROOT" "dist/qdstar_${VERSION}_${ARCH}.deb"
