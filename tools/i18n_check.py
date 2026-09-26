"""Check translations: list tr() texts missing from each translations/<lang>.po.

Usage:
    python tools/i18n_check.py            # report per language
    python tools/i18n_check.py --template # print a .po template with every text (for a new language)
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from qdstar.i18n import TRANSLATIONS_DIR, _parse_po  # noqa: E402


def po_quote(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def source_texts():
    """Every literal passed to tr() or N_() in the package."""
    texts = {}
    for path in sorted((ROOT / "qdstar").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("tr", "N_") and node.args
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                texts.setdefault(node.args[0].value, f"{path.relative_to(ROOT)}:{node.lineno}")
    return texts


def main():
    texts = source_texts()
    if "--template" in sys.argv:
        print('msgid ""\nmsgstr ""\n"Language-Name: <name>\\n"\n')
        for text, where in texts.items():
            print(f"#: {where}\nmsgid {po_quote(text)}\nmsgstr \"\"\n")
        return 0
    status = 0
    for po in sorted(TRANSLATIONS_DIR.glob("*.po")):
        entries = _parse_po(po)
        missing = [t for t in texts if not entries.get(t)]
        unused = [t for t in entries if t and t not in texts]
        print(f"{po.name}: {len(texts) - len(missing)}/{len(texts)} translated, {len(unused)} unused")
        for t in missing:
            print(f"  missing: {texts[t]}  {t!r}")
        for t in unused:
            print(f"  unused:  {t!r}")
        status |= bool(missing)
    return status


if __name__ == "__main__":
    sys.exit(main())
