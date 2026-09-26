#!/bin/sh
# Build an AppImage from the PyInstaller one-folder output.
# Usage: packaging/build_appimage.sh <version> <appimage-arch: x86_64|aarch64>
set -eu
VERSION="$1"
ARCH="$2"
APPDIR="build/QDStar.AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr"
cp -a dist/qdstar "$APPDIR/usr/qdstar"
cp packaging/qdstar.desktop "$APPDIR/qdstar.desktop"
cp packaging/qdstar.png "$APPDIR/qdstar.png"
cat > "$APPDIR/AppRun" <<'RUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/qdstar/qdstar" "$@"
RUN
chmod +x "$APPDIR/AppRun"
TOOL="build/appimagetool-${ARCH}.AppImage"
if [ ! -x "$TOOL" ]; then
  curl -sSL -o "$TOOL" "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage"
  chmod +x "$TOOL"
fi
ARCH="$ARCH" "$TOOL" --appimage-extract-and-run "$APPDIR" "dist/QDStar-${VERSION}-${ARCH}.AppImage"
