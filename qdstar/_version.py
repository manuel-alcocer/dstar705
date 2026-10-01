"""Version of this copy of QDStar.

Releases are numbered in CI by semantic-release from the commit messages
(.releaserc.json); tools/set_version.py writes the number into RELEASE before a
build. A checkout has no number of its own and takes it from the nearest git tag.
"""

import subprocess
from pathlib import Path

RELEASE = ""   # filled in by tools/set_version.py


def _from_git():
    """'0.8.1' on a tag, '0.8.1+3.g1a2b3c4' three commits after it."""
    try:
        text = subprocess.run(["git", "describe", "--tags", "--long", "--match", "[0-9]*"],
                              cwd=Path(__file__).parent, capture_output=True, text=True,
                              timeout=5, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "0.0.0+unknown"
    tag, commits, commit = text.rsplit("-", 2)
    return tag if commits == "0" else f"{tag}+{commits}.{commit}"


__version__ = RELEASE or _from_git()
