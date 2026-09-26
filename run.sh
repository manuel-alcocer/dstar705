#!/bin/sh
# Start QDStar with the system Python (PySide6 from the distro packages).
cd "$(dirname "$0")" && exec /usr/bin/python3 -m qdstar "$@"
