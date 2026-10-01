"""Delete the GitHub releases that newer ones have replaced (run by CI after a public release).

What stays:
  - every release of the current line (the major.minor of the latest public version),
  - the latest release of each earlier minor line of the current major,
  - the latest release of each earlier major,
  - the pre-releases (beta, rc) of versions later than the latest public one.

Only the releases and their downloads are deleted: the git tags stay.

Usage (needs the gh CLI, logged in):
    python tools/prune_releases.py            # list what would be deleted
    python tools/prune_releases.py --delete   # delete it
"""

import json
import re
import subprocess
import sys

VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)(-.+)?")


def gh(*args):
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout


def obsolete(releases):
    """Tags to delete among releases, a list of (tag, is_prerelease)."""
    stable, pre = {}, {}
    for tag, prerelease in releases:
        match = VERSION.fullmatch(tag)
        if not match:
            continue    # not one of ours: leave it alone
        number = tuple(int(n) for n in match.groups()[:3])
        (pre if prerelease or match.group(4) else stable)[tag] = number
    if not stable:
        return []
    latest = max(stable.values())
    keep = set()
    for tag, number in stable.items():
        if number[:2] == latest[:2]:
            keep.add(tag)
            continue
        # earlier lines: one per minor in the current major, one per earlier major
        line = number[:2] if number[0] == latest[0] else number[:1]
        if number == max(n for n in stable.values() if n[:len(line)] == line):
            keep.add(tag)
    doomed = [tag for tag in stable if tag not in keep]
    doomed += [tag for tag, number in pre.items() if number <= latest]
    return sorted(doomed, key=lambda tag: (stable.get(tag) or pre[tag], tag))


def main():
    listed = json.loads(gh("release", "list", "--limit", "1000", "--json", "tagName,isPrerelease,isDraft"))
    doomed = obsolete([(r["tagName"], r["isPrerelease"]) for r in listed if not r["isDraft"]])
    delete = "--delete" in sys.argv
    for tag in doomed:
        print(("deleting " if delete else "would delete ") + tag)
        if delete:
            gh("release", "delete", tag, "--yes")
    if not doomed:
        print("nothing to delete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
