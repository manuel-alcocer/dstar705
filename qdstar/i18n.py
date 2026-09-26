"""User interface translations.

Texts are written in English in the code and wrapped in tr(). Each language has
one plain-text gettext-style file in translations/ (e.g. es.po):

    msgid "Linked to {reflector}"
    msgstr "Enlazado a {reflector}"

Placeholders in braces are filled with str.format(). Missing entries fall back
to English. To add a language, copy es.po to <code>.po and translate the msgstr
lines; the header's "Language-Name" is shown in the settings.
"""

import ast
from pathlib import Path

from PySide6.QtCore import QLocale

TRANSLATIONS_DIR = Path(__file__).with_name("translations")

_catalog = {}
_language = "en"


def _parse_po(path):
    """Minimal .po reader: msgid/msgstr pairs with continuation lines; comments ignored."""
    entries = {}
    msgid = msgstr = None
    target = None

    def flush():
        if msgid is not None and msgstr is not None:
            entries[msgid] = msgstr

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("msgid "):
            flush()
            msgid, msgstr, target = ast.literal_eval(line[6:]), None, "id"
        elif line.startswith("msgstr "):
            msgstr, target = ast.literal_eval(line[7:]), "str"
        elif line.startswith('"'):
            part = ast.literal_eval(line)
            if target == "id":
                msgid += part
            elif target == "str":
                msgstr += part
    flush()
    return entries


def _header(entries):
    fields = {}
    for line in entries.get("", "").splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def available_languages():
    """{'en': 'English', 'es': 'Español', ...}"""
    languages = {"en": "English"}
    for po in sorted(TRANSLATIONS_DIR.glob("*.po")):
        try:
            languages[po.stem] = _header(_parse_po(po)).get("Language-Name", po.stem)
        except (OSError, ValueError, SyntaxError):
            continue
    return languages


def system_language():
    return QLocale.system().name().split("_")[0] or "en"


def set_language(code=None):
    """Load a language ('es'); None/'' = the system language. Unknown languages fall back to English."""
    global _catalog, _language
    code = (code or system_language()).lower()
    path = TRANSLATIONS_DIR / f"{code}.po"
    if code != "en" and path.exists():
        entries = _parse_po(path)
        _catalog = {k: v for k, v in entries.items() if k and v}
        _language = code
    else:
        _catalog = {}
        _language = "en"
    return _language


def language():
    return _language


def N_(text):
    """Mark a text for translation where it is defined; tr() translates it when shown."""
    return text


def tr(text, **values):
    """Translated text; placeholders like {reflector} are filled from the keyword arguments."""
    translated = _catalog.get(text, text)
    return translated.format(**values) if values else translated
