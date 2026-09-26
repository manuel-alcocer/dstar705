#!/bin/sh
# Build an AppImage from the PyInstaller one-folder output.
# Usage: packaging/build_appimage.sh <version> <appimage-arch: x86_64|aarch64>
set -eu
VERSION="$1"
ARCH="$2"
APPDIR="build/DStar705.AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr"
cp -a dist/dstar705 "$APPDIR/usr/dstar705"
cp packaging/dstar705.desktop "$APPDIR/dstar705.desktop"
cp packaging/dstar705.png "$APPDIR/dstar705.png"
cat > "$APPDIR/AppRun" <<'RUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/dstar705/dstar705" "$@"
RUN
chmod +x "$APPDIR/AppRun"
TOOL="build/appimagetool-${ARCH}.AppImage"
if [ ! -x "$TOOL" ]; then
  curl -sSL -o "$TOOL" "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage"
  chmod +x "$TOOL"
fi
ARCH="$ARCH" "$TOOL" --appimage-extract-and-run "$APPDIR" "dist/DStar705-${VERSION}-${ARCH}.AppImage"
