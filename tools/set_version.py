"""Write the version of a build into qdstar/_version.py (run by CI before PyInstaller).

Usage:
    python tools/set_version.py 0.9.0-beta.1
"""

import re
import sys
from pathlib import Path

VERSION_FILE = Path(__file__).resolve().parent.parent / "qdstar" / "_version.py"


def main():
    if len(sys.argv) != 2 or not re.fullmatch(r"\d+\.\d+\.\d+([-+][0-9A-Za-z.+-]+)?", sys.argv[1]):
        print(__doc__)
        return 2
    source = VERSION_FILE.read_text(encoding="utf-8")
    changed, count = re.subn(r'^RELEASE = ""', f'RELEASE = "{sys.argv[1]}"', source, flags=re.M)
    if count != 1:
        print(f"RELEASE line not found in {VERSION_FILE}")
        return 1
    VERSION_FILE.write_text(changed, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
